import boto3
import botocore
import operator
import json
import os

SOURCE_REGION = os.environ.get('SOURCE_REGION')
TARGET_REGION = os.environ.get('TARGET_REGION')
SOURCE_CLIENT = boto3.client('rds', SOURCE_REGION)
TARGET_CLIENT = boto3.client('rds', TARGET_REGION)


def copy_latest_snapshot(account_id, instance_name):
    # Get a list of automated snapshots for this database
    response = SOURCE_CLIENT.describe_db_snapshots(
        DBInstanceIdentifier=instance_name,
        SnapshotType="automated"
    )

    if len(response['DBSnapshots']) == 0:
        raise Exception("No automated snapshots found for database " + instance_name)

    # Order the list of snapshots by creation time
    snapshots = {}
    for snapshot in response['DBSnapshots']:
        if snapshot['Status'] != 'available':
            continue

        snapshots[snapshot['DBSnapshotIdentifier']] = snapshot['SnapshotCreateTime']

    # Get the latest snapshot
    snapshot_name, snapshot_time = sorted(snapshots.items(), key=operator.itemgetter(1)).pop()
    copy_name = "{}-{}-{}".format(instance_name, SOURCE_REGION, snapshot_name)
    print("Latest snapshot found: '{}' from {}".format(snapshot_name, snapshot_time))
    print("Checking if '{}' already exists in target region".format(copy_name))

    # Look for the copy_name snapshot in target region
    try:
        TARGET_CLIENT.describe_db_snapshots(
            DBSnapshotIdentifier=copy_name
        )
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "DBSnapshotNotFound":
            source_snapshot_arn = "arn:aws:rds:{}:{}:snapshot:{}".format(SOURCE_REGION, account_id, snapshot_name)
            response = TARGET_CLIENT.copy_db_snapshot(
                SourceDBSnapshotIdentifier=source_snapshot_arn,
                TargetDBSnapshotIdentifier=copy_name,
                CopyTags=True
            )

            # Check the status of the copy
            if response['DBSnapshot']['Status'] not in ("pending", "available"):
                raise Exception("Copy operation for {} failed!".format(copy_name))

            print("Successfully copied {} to {}", format(copy_name, TARGET_REGION))
        else:
            print("{} is already copied to {}".format(copy_name, TARGET_REGION))


def remove_old_snapshots(instance_name):
    # Get a list of all snapshots for this database in target region
    response = TARGET_CLIENT.describe_db_snapshots(
        SnapshotType='manual',
        DBInstanceIdentifier=instance_name
    )

    if len(response['DBSnapshots']) == 0:
        raise Exception("No snapshots for database {} found in target region".format(instance_name))

    # List the snapshots by time created
    snapshots = {}
    for snapshot in response['DBSnapshots']:
        if snapshot['Status'] != 'available':
            continue
        snapshots[snapshot['DBSnapshotIdentifier']] = snapshot['SnapshotCreateTime']

    # Sort snapshots by time and get all other than the latest one
    if len(snapshots) > 1:
        sorted_snapshots = sorted(snapshots.items(), key=operator.itemgetter(1), reverse=True)
        snapshots_to_remove = [i[0] for i in sorted_snapshots[1:]]
        print("Found {} snapshot(s) to remove".format(len(snapshots_to_remove)))

        # Remove the snapshots
        for snapshot in snapshots_to_remove:
            print("Removing {}".format(snapshot))
            TARGET_CLIENT.delete_db_snapshot(
                DBSnapshotIdentifier=snapshot
            )
    else:
        print("No old snapshots to remove in target region")


def lambda_handler(event, context):
    account_id = context.invoked_function_arn.split(":")[4]
    message = json.loads(event['Records'][0]['Sns']['Message'])

    # Check that event reports backup has finished
    event_id = message['Event ID'].split("#")
    if event_id[1] == 'RDS-EVENT-0002':
        copy_latest_snapshot(account_id, message['Source ID'])
        remove_old_snapshots(message['Source ID'])
    else:
        print("Skipping")
