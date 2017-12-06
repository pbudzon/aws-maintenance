import boto3
import operator

aws_account = 'XXXX'
source = 'us-east-1'
destination = 'sa-east-1'

def getDBs():
    rdsclient = boto3.client('rds', source)

    databases = rdsclient.describe_db_instances()
    DBArray=[]
    for database in databases['DBInstances']:
        DBArray.append(database['DBInstanceIdentifier'])

    return DBArray

databases = getDBs()

def copy_latest_snapshot():
    client = boto3.client('rds', source)
    foreign_client = boto3.client('rds', destination)

    response = client.describe_db_snapshots(
        SnapshotType='automated',
        IncludeShared=False,
        IncludePublic=False
    )

    if len(response['DBSnapshots']) == 0:
        raise Exception("No automated snapshots found")

    snapshots_per_project = {}

    for snapshot in response['DBSnapshots']:
        if snapshot['DBInstanceIdentifier'] not in databases or snapshot['Status'] != 'available' :
            continue

        if snapshot['DBInstanceIdentifier'] not in snapshots_per_project.keys():
            snapshots_per_project[snapshot['DBInstanceIdentifier']] = {}

        snapshots_per_project[snapshot['DBInstanceIdentifier']][snapshot['DBSnapshotIdentifier']] = snapshot[
            'SnapshotCreateTime']

    for project in snapshots_per_project:
        sorted_list = sorted(snapshots_per_project[project].items(), key=operator.itemgetter(1), reverse=True)

        copy_name = project + "-" + sorted_list[0][1].strftime("%Y-%m-%d")

        print("Checking if " + copy_name + " is copied")

        try:
            foreign_client.describe_db_snapshots(
                DBSnapshotIdentifier=copy_name
            )
        except:
            response = foreign_client.copy_db_snapshot(
                SourceDBSnapshotIdentifier='arn:aws:rds:' + source + ':' + aws_account + ':snapshot:' + sorted_list[0][0],
                TargetDBSnapshotIdentifier=copy_name,
                CopyTags=True
            )

            if response['DBSnapshot']['Status'] != "pending" and response['DBSnapshot']['Status'] != "available":
                raise Exception("Copy operation for " + copy_name + " failed!")
            print("Copied " + copy_name)

            continue

        print("Already copied")


def remove_old_snapshots():
    client = boto3.client('rds', source)
    foreign_client = boto3.client('rds', destination)

    response = foreign_client.describe_db_snapshots(
        SnapshotType='manual'
    )

    if len(response['DBSnapshots']) == 0:
        raise Exception("No manual snapshots in "+ destination + " found")

    snapshots_per_project = {}
    for snapshot in response['DBSnapshots']:
        if snapshot['DBInstanceIdentifier'] not in databases or snapshot['Status'] != 'available' :
            continue

        if snapshot['DBInstanceIdentifier'] not in snapshots_per_project.keys():
            snapshots_per_project[snapshot['DBInstanceIdentifier']] = {}

        snapshots_per_project[snapshot['DBInstanceIdentifier']][snapshot['DBSnapshotIdentifier']] = snapshot[
            'SnapshotCreateTime']

    for project in snapshots_per_project:
        if len(snapshots_per_project[project]) > 1:
            sorted_list = sorted(snapshots_per_project[project].items(), key=operator.itemgetter(1), reverse=True)
            to_remove = [i[0] for i in sorted_list[1:]]

            for snapshot in to_remove:
                print("Removing " + snapshot)
                foreign_client.delete_db_snapshot(
                    DBSnapshotIdentifier=snapshot
                )

def lambda_handler(event, context):
    copy_latest_snapshot()
    remove_old_snapshots()


if __name__ == '__main__':
    lambda_handler(None, None)
