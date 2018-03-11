# The MIT License (MIT)
#
# Copyright (c) 2016 Paulina Budzoń <https://github.com/pbudzon>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime

import boto3

EC2_CLIENT = boto3.client("ec2")
EC2_RESOURCE = boto3.resource("ec2")
TODAY = datetime.date.today()

# How long to keep backups for by default
DEFAULT_RETENTION = 7
# Name of the tag indicating which instances to backup
BACKUP_TAG = "Backup"
# Name of the tag indicating deletion date for snapshots
DELETE_ON_TAG = "DeleteOn"


def get_retention_period(instance):
    """
    Finds "Backup" tag in list of tags or returns default period (7 days)
    :param instance: dict Dictionary output with instance details from describe_instances call
    :return: Retention period for that instance
    """
    for tag in instance["Tags"]:
        if tag["Key"] == BACKUP_TAG:
            days = int(tag["Value"])
            if days > 0:
                return days
            else:
                print("Retention period of {} makes no sense, using default".format(days))

    return DEFAULT_RETENTION  # default


def find_delete_tag(tags):
    """
    Finds "DeleteOn" tag within the list of tags and returns it as a date object
    :param tags: List of tags from instance describe_instances call
    :return: None if tag was not found or date object
    """
    delete_date = None
    if tags:
        for tag in tags:
            if tag["Key"] == DELETE_ON_TAG:
                delete_date = datetime.datetime.strptime(tag["Value"], "%Y-%m-%d").date()

    return delete_date


def is_already_snapshoted(volume):
    """
    Check is volume already had snapshot created by us today
    :param volume: ec2.Volume object from boto3 for the volume in question
    :return: True/False whether the snapshot exists
    """
    snapshots = volume.snapshots.all()
    for snapshot in snapshots:
        if snapshot.start_time.date() == TODAY and snapshot.state in ("pending", "completed") and \
                find_delete_tag(snapshot.tags) is not None:
            return True

    return False


def create_snapshots(context):
    """
    Find instances to backup and create their snapshots
    :param context: Lambda context object
    """
    paginator = EC2_CLIENT.get_paginator("describe_instances")

    response_iterator = paginator.paginate(
        Filters=[
            {"Name": "tag-key", "Values": [BACKUP_TAG]},
        ]
    )

    for instances in response_iterator:
        for reservations in instances["Reservations"]:
            for instance in reservations["Instances"]:
                for device in instance["BlockDeviceMappings"]:
                    # Look at every EBS volume attached to this instance
                    if "Ebs" in device:
                        # Get volume and check if snapshot already exists
                        volume = EC2_RESOURCE.Volume(device["Ebs"]["VolumeId"])
                        if is_already_snapshoted(volume):
                            print("Already done today: volume {} on instance {}, skipping".format(volume.id, instance[
                                "InstanceId"]))
                            continue

                        print("Found EBS volume {} on instance {}".format(volume.id, instance["InstanceId"]))

                        # Create the snapshot
                        snapshot = volume.create_snapshot(
                            Description="Snapshot from instance {}".format(instance["InstanceId"])
                        )

                        # Get how many days we should keep this snapshot for
                        retention_days = get_retention_period(instance)

                        # Get instance tags and remove the "backup" tag
                        tags = instance["Tags"]
                        for tag in tags:
                            if tag["Key"] == BACKUP_TAG:
                                tags.remove(tag)
                                break

                        # Find date when to delete and add the tag to the list
                        delete_date = datetime.date.today() + datetime.timedelta(days=retention_days)
                        tags.append(
                            {
                                "Key": DELETE_ON_TAG,
                                "Value": delete_date.strftime("%Y-%m-%d")
                            }
                        )
                        # Add function name to the tags for reference who created the snapshot
                        tags.append(
                            {
                                "Key": "CreatedBy",
                                "Value": context.function_name
                            }
                        )

                        # Apply all those tags to the snapshot
                        snapshot.create_tags(Tags=tags)

                        print("Retaining snapshot {} of volume {} from instance {} until {}".format(
                            snapshot.id, volume.id, instance["InstanceId"], delete_date
                        ))


def remove_snapshots():
    """
    Find our old snapshots and remove as needed (when DeleteOn is today or earlier)
    """
    paginator = EC2_CLIENT.get_paginator("describe_snapshots")
    response_iterator = paginator.paginate(
        Filters=[
            {"Name": "tag-key", "Values": [DELETE_ON_TAG]},
        ],
    )

    for snapshots in response_iterator:
        for snapshot in snapshots["Snapshots"]:
            delete_date = find_delete_tag(snapshot["Tags"])

            if delete_date is not None and delete_date <= TODAY:
                print("Deleting old snapshot: {}".format(snapshot["SnapshotId"]))
                EC2_CLIENT.delete_snapshot(
                    SnapshotId=snapshot["SnapshotId"],
                )


def lambda_handler(event, context):
    create_snapshots(context)
    remove_snapshots()
