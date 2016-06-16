import json
import boto3
import gzip


def lambda_handler(event, context):
    sns_topic = None

    info = boto3.client('lambda').get_function(
        FunctionName=context.function_name
    )

    iam = boto3.client('iam')
    role_name = info['Configuration']['Role'].split('/')[1]

    policies = iam.list_role_policies(
        RoleName=role_name
    )

    for policy in policies['PolicyNames']:
        details = iam.get_role_policy(
            RoleName=role_name,
            PolicyName=policy
        )

        for statement in details['PolicyDocument']['Statement']:
            for action in statement['Action']:
                if action == 'sns:publish':
                    sns_topic = statement['Resource']
                    break

    if sns_topic is None:
        raise Exception("Could not find SNS topic for notifications!")

    sns = boto3.client('sns')

    if 'Records' not in event:
        raise Exception("Invalid message received!")

    for record in event['Records']:
        if 'Message' not in record['Sns']:
            print("invalid record!")
            print(record)

        message = json.loads(record['Sns']['Message'])

        if 's3Bucket' not in message or 's3ObjectKey' not in message:
            raise Exception("s3Bucket or s3ObjectKey missing from Message!")

        s3 = boto3.resource('s3')

        for s3key in message['s3ObjectKey']:
            s3.meta.client.download_file(message['s3Bucket'], s3key, '/tmp/s3file.json.gz')

            with gzip.open('/tmp/s3file.json.gz', 'rb') as f:
                file_content = json.loads(f.read())
                for record in file_content['Records']:
                    if record['eventSource'] == "ec2.amazonaws.com" and record['eventName'] == 'RunInstances':
                        print(record)
                        for topic in sns_topic:
                            sns.publish(
                                TopicArn=topic,
                                Message=json.dumps(record),
                                Subject="RunInstances invoked at " + record['eventTime']
                            )


if __name__ == '__main__':
    lambda_handler({
        "Records": [{
            "Sns": {
                "Message": "{\"s3Bucket\":\"cloudtrail-xxx\",\"s3ObjectKey\":[\"AWSLogs/xxx/CloudTrail/ap-northeast-1/2016/06/15/abc.json.gz\"]}"
            }
        }]
    }, None)
