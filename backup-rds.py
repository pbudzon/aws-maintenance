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

import json
import operator
import os

import boto3
import botocore

# Env variables
SOURCE_REGION = os.environ.get("SOURCE_REGION")
TARGET_REGION = os.environ.get("TARGET_REGION")
KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "")

# Global clients
SOURCE_CLIENT = boto3.client("rds", SOURCE_REGION)
TARGET_CLIENT = boto3.client("rds", TARGET_REGION)


def get_snapshots_list(response, is_aurora):
    """
    Simplifies list of snapshots by retaining snapshot name and creation time only
    :param response: dict Output from describe_db_snapshots or describe_db_cluster_snapshots
    :param is_aurora: bool True if output if from describe_db_cluster_snapshots, False otherwise
    :return: Dict with snapshot id as key and snapshot creation time as value
    """
    snapshots = {}

    response_list_key = "DBClusterSnapshots" if is_aurora else "DBSnapshots"
    identifier_list_key = "DBClusterSnapshotIdentifier" if is_aurora else "DBSnapshotIdentifier"
    for snapshot in response[response_list_key]:
        if snapshot["Status"] != "available":
            continue

        snapshots[snapshot[identifier_list_key]] = snapshot["SnapshotCreateTime"]

    return snapshots


def print_encryption_info(source_snapshot_arn, is_aurora):
    """
    Prints out info about encryption for the snapshot copy. Can be skipped completely, only used for more detailed logs.
    :param source_snapshot_arn: string ARN of the source snapshot
    :param is_aurora: bool True it it's Aurora cluster snapshot, False otherwise
    :return: None
    """
    if is_aurora:
        snapshot_details = SOURCE_CLIENT.describe_db_cluster_snapshots(
            DBClusterSnapshotIdentifier=source_snapshot_arn,
        )
    else:
        snapshot_details = SOURCE_CLIENT.describe_db_snapshots(
            DBSnapshotIdentifier=source_snapshot_arn,
        )

    # No key, but snapshot is encrypted
    if KMS_KEY_ID == "" and (
            (not is_aurora and snapshot_details["DBSnapshots"][0]["Encrypted"]) or
            (is_aurora and snapshot_details["DBClusterSnapshots"][0]["StorageEncrypted"])
    ):
        raise Exception(
            "Snapshot is encrypted, but no encryption key specified for copy! " +
            "Set KMS Key ID parameter in CloudFormation stack")

    # Key provided, but snapshot not encrypted (notice only)
    if KMS_KEY_ID != "" and (
            (not is_aurora and not snapshot_details["DBSnapshots"][0]["Encrypted"]) or
            (is_aurora and not snapshot_details["DBClusterSnapshots"][0]["StorageEncrypted"])
    ):
        print("Snapshot is not encrypted, but KMS key specified - copy WILL BE encrypted")


def get_clusters(clusters_to_use):
    """
    Gets a list of Aurora clusters and matches that against CLUSTERS_TO_USE env variable (if provided).
    :param clusters_to_use: List of cluster names
    :return: List of Aurora cluster names that match CLUSTERS_TO_USE (or all, if CLUSTERS_TO_USE is empty)
    """
    clusters = []
    clusters_list = SOURCE_CLIENT.describe_db_clusters()
    for cluster in clusters_list['DBClusters']:
        if (clusters_to_use and cluster['DBClusterIdentifier'] in clusters_to_use) or (not clusters_to_use):
            clusters.append(cluster['DBClusterIdentifier'])

    return clusters


def copy_latest_snapshot(account_id, instance_name, is_aurora):
    """
    Finds the latest snapshot for a given RDS instance/Aurora Cluster and copies it to target region.
    :param account_id: int ID of the current AWS account
    :param instance_name: string Name of the instance/cluster
    :param is_aurora: bool True if instance_name is name of Aurora cluster, False otherwise
    :return: None
    :raises Exception if instance/cluster has no automated snapshots or copy operation fails
    """

    # Get a list of automated snapshots for this database
    if is_aurora:
        response = SOURCE_CLIENT.describe_db_cluster_snapshots(
            DBClusterIdentifier=instance_name,
            SnapshotType="automated"
        )
        if len(response["DBClusterSnapshots"]) == 0:
            raise Exception("No automated snapshots found for cluster " + instance_name)
    else:
        response = SOURCE_CLIENT.describe_db_snapshots(
            DBInstanceIdentifier=instance_name,
            SnapshotType="automated"
        )

        if len(response["DBSnapshots"]) == 0:
            raise Exception("No automated snapshots found for database " + instance_name)

    # Order the list of snapshots by creation time
    snapshots = get_snapshots_list(response, is_aurora)

    # Get the latest snapshot
    snapshot_name, snapshot_time = sorted(snapshots.items(), key=operator.itemgetter(1)).pop()
    print("Latest snapshot found: '{}' from {}".format(snapshot_name, snapshot_time))
    copy_name = "{}-{}-{}".format(instance_name, SOURCE_REGION, snapshot_name.replace(":", "-"))
    print("Checking if '{}' exists in target region".format(copy_name))

    # Look for the copy_name snapshot in target region
    try:
        if is_aurora:
            TARGET_CLIENT.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=copy_name
            )
        else:
            TARGET_CLIENT.describe_db_snapshots(
                DBSnapshotIdentifier=copy_name
            )

        print("{} is already copied to {}".format(copy_name, TARGET_REGION))
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] in ("DBSnapshotNotFound", "DBClusterSnapshotNotFoundFault"):
            snapshot_arn_name = "cluster-snapshot" if is_aurora else "snapshot"
            source_snapshot_arn = "arn:aws:rds:{}:{}:{}:{}".format(SOURCE_REGION, account_id, snapshot_arn_name,
                                                                   snapshot_name)

            print_encryption_info(source_snapshot_arn, is_aurora)

            # Trigger a copy operation
            if is_aurora:
                response_list_key = "DBClusterSnapshot"
                response = TARGET_CLIENT.copy_db_cluster_snapshot(
                    SourceDBClusterSnapshotIdentifier=source_snapshot_arn,
                    TargetDBClusterSnapshotIdentifier=copy_name,
                    CopyTags=True,
                    KmsKeyId=KMS_KEY_ID,
                    SourceRegion=SOURCE_REGION
                )
            else:
                response_list_key = "DBSnapshot"
                response = TARGET_CLIENT.copy_db_snapshot(
                    SourceDBSnapshotIdentifier=source_snapshot_arn,
                    TargetDBSnapshotIdentifier=copy_name,
                    CopyTags=True,
                    KmsKeyId=KMS_KEY_ID,
                    SourceRegion=SOURCE_REGION  # Ref: https://github.com/boto/botocore/issues/1273
                )

            # Check the status of the copy
            if response[response_list_key]["Status"] not in ("pending", "available", "copying"):
                raise Exception("Copy operation for {} failed!".format(copy_name))

            print("Copied {} to {}".format(copy_name, TARGET_REGION))
            return
        else:  # Another error happened, re-raise
            raise e


def remove_old_snapshots(instance_name, is_aurora):
    """
    Finds previously-copied snapshots for given RDS instance / Aurora cluster in target regions and leaves only latest one.
    :param instance_name: string Name of the instance/cluster
    :param is_aurora: bool True if instance_name is name of Aurora cluster, False otherwise
    :return: None
    :raises Exception if instance/cluster has no snapshots in target region
    """

    # Get a list of all snapshots for this database in target region
    if is_aurora:
        response = TARGET_CLIENT.describe_db_cluster_snapshots(
            SnapshotType="manual",
            DBClusterIdentifier=instance_name
        )

        if len(response["DBClusterSnapshots"]) == 0:
            raise Exception("No snapshots for cluster {} found in target region".format(instance_name))
    else:
        response = TARGET_CLIENT.describe_db_snapshots(
            SnapshotType="manual",
            DBInstanceIdentifier=instance_name
        )

        if len(response["DBSnapshots"]) == 0:
            raise Exception("No snapshots for database {} found in target region".format(instance_name))

    # List the snapshots by time created
    snapshots = get_snapshots_list(response, is_aurora)

    # Sort snapshots by time and get all other than the latest one
    if len(snapshots) > 1:
        sorted_snapshots = sorted(snapshots.items(), key=operator.itemgetter(1), reverse=True)
        snapshots_to_remove = [i[0] for i in sorted_snapshots[1:]]
        print("Found {} snapshot(s) to remove".format(len(snapshots_to_remove)))

        # Remove the snapshots
        for snapshot in snapshots_to_remove:
            print("Removing {}".format(snapshot))
            if is_aurora:
                TARGET_CLIENT.delete_db_cluster_snapshot(
                    DBClusterSnapshotIdentifier=snapshot
                )
            else:
                TARGET_CLIENT.delete_db_snapshot(
                    DBSnapshotIdentifier=snapshot
                )
    else:
        print("No old snapshots to remove in target region")


def lambda_handler(event, context):
    account_id = context.invoked_function_arn.split(":")[4]

    # Scheduled event for Aurora
    if 'source' in event and event['source'] == "aws.events":
        clusters_to_use = os.environ.get("CLUSTERS_TO_USE", None)
        if clusters_to_use:
            clusters_to_use = clusters_to_use.split(",")
        clusters = get_clusters(clusters_to_use)

        if len(clusters) == 0:
            raise Exception("No matching clusters found")

        for cluster in clusters:
            copy_latest_snapshot(account_id, cluster, True)
            remove_old_snapshots(cluster, True)

    else:  # Assume SNS about instance backup
        message = json.loads(event["Records"][0]["Sns"]["Message"])

        # Check that event reports backup has finished
        event_id = message["Event ID"].split("#")
        if event_id[1] == "RDS-EVENT-0002":
            copy_latest_snapshot(account_id, message["Source ID"], False)
            remove_old_snapshots(message["Source ID"], False)
