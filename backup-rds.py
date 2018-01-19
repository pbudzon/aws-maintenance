import json
import operator
import os

import boto3
import botocore

# Env variables
SOURCE_REGION = os.environ.get('SOURCE_REGION')
TARGET_REGION = os.environ.get('TARGET_REGION')
KMS_KEY_ID = os.environ.get('KMS_KEY_ID', "")

# Global clients
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
    print("Latest snapshot found: '{}' from {}".format(snapshot_name, snapshot_time))
    copy_name = "{}-{}-{}".format(instance_name, SOURCE_REGION, snapshot_name.replace(":", "-"))
    print("Checking if '{}' exists in target region".format(copy_name))

    # Look for the copy_name snapshot in target region
    try:
        TARGET_CLIENT.describe_db_snapshots(
            DBSnapshotIdentifier=copy_name
        )

        print("{} is already copied to {}".format(copy_name, TARGET_REGION))
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "DBSnapshotNotFound":
            source_snapshot_arn = "arn:aws:rds:{}:{}:snapshot:{}".format(SOURCE_REGION, account_id, snapshot_name)
            snapshot_details = SOURCE_CLIENT.describe_db_snapshots(
                DBSnapshotIdentifier=source_snapshot_arn,
            )

            # No key, but snapshot is encrypted
            if snapshot_details['DBSnapshots'][0]['Encrypted'] and KMS_KEY_ID == "":
                raise Exception(
                    "Snapshot is encrypted, but no encryption key specified for copy! " +
                    "Set KMS Key ID parameter in CloudFormation stack")

            # Key provided, but snapshot not encrypted (notice only)
            if KMS_KEY_ID != "" and not snapshot_details['DBSnapshots'][0]['Encrypted']:
                print("Snapshot is not encrypted, but KMS key specified - copy WILL BE encrypted")

            # Trigger a copy operation
            response = TARGET_CLIENT.copy_db_snapshot(
                SourceDBSnapshotIdentifier=source_snapshot_arn,
                TargetDBSnapshotIdentifier=copy_name,
                CopyTags=True,
                KmsKeyId=KMS_KEY_ID,
                SourceRegion=SOURCE_REGION  # Ref: https://github.com/boto/botocore/issues/1273
            )

            # Check the status of the copy
            if response['DBSnapshot']['Status'] not in ("pending", "available"):
                raise Exception("Copy operation for {} failed!".format(copy_name))

            print("Copied {} to {}".format(copy_name, TARGET_REGION))
            return
        else:  # Another error happened, re-raise
            raise e


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
