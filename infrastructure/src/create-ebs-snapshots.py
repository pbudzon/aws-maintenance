from awacs import aws, sts
from troposphere import Template, GetAtt, Ref, Parameter
from troposphere import awslambda, iam, events

template = Template()

template.add_description("Automated EBS snapshots and retention management")

s3_bucket_parameter = template.add_parameter(Parameter(
    "S3BucketParameter",
    Type="String",
    Description="Name of the S3 bucket where you uploaded the source code zip",
))

source_zip_parameter = template.add_parameter(Parameter(
    "SourceZipParameter",
    Type="String",
    Default="ebs-snapshots.zip",
    Description="Name of the zip file inside the S3 bucket",
))

template.add_metadata({
    "AWS::CloudFormation::Interface": {
        "ParameterGroups": [
            {
                "Label": {
                    "default": "Basic configuration"
                },
                "Parameters": [
                    "S3BucketParameter",
                    "SourceZipParameter",
                ]
            },
        ],
        "ParameterLabels": {
            "S3BucketParameter": {"default": "Name of S3 bucket"},
            "SourceZipParameter": {"default": "Name of ZIP file"},
        }
    }
})

# Role for Lambda
lambda_role = template.add_resource(iam.Role(
    "LambdaRole",
    AssumeRolePolicyDocument=aws.Policy(
        Statement=[
            aws.Statement(
                Effect=aws.Allow,
                Action=[sts.AssumeRole],
                Principal=aws.Principal(
                    "Service", ["lambda.amazonaws.com"]
                )
            )
        ]
    ),
    Policies=[iam.Policy(
        "LambdaBackupRDSPolicy",
        PolicyName="AccessToEC2Snapshots",
        PolicyDocument=aws.Policy(Statement=[
            aws.Statement(
                Effect=aws.Allow,
                Action=[
                    aws.Action("ec2", "Describe*"),
                    aws.Action("ec2", "CreateSnapshot"),
                    aws.Action("ec2", "DeleteSnapshot"),
                    aws.Action("ec2", "CreateTags"),
                    aws.Action("ec2", "ModifySnapshotAttribute"),
                    aws.Action("ec2", "ResetSnapshotAttribute"),
                ],
                Resource=["*"]
            ),
            aws.Statement(
                Effect=aws.Allow,
                Action=[
                    aws.Action("logs", "CreateLogGroup"),
                    aws.Action("logs", "CreateLogStream"),
                    aws.Action("logs", "PutLogEvents"),
                ],
                Resource=["arn:aws:logs:*:*:*"]
            ),
        ])
    )]
))

lambda_function = template.add_resource(awslambda.Function(
    "LambdaFunction",
    Description="Maintains EBS snapshots of tagged instances",
    Code=awslambda.Code(
        S3Bucket=Ref(s3_bucket_parameter),
        S3Key=Ref(source_zip_parameter),
    ),
    Handler="ebs-snapshots.lambda_handler",
    MemorySize=128,
    Role=GetAtt(lambda_role, "Arn"),
    Runtime="python3.6",
    Timeout=30
))

schedule_event = template.add_resource(events.Rule(
    "LambdaTriggerRule",
    Description="Trigger EBS snapshot Lambda",
    ScheduleExpression="rate(1 day)",
    State="ENABLED",
    Targets=[
        events.Target(
            Arn=GetAtt(lambda_function, "Arn"),
            Id="ebs-snapshot-lambda"
        )
    ]
))

# Permission for CloudWatch Events to trigger the Lambda
template.add_resource(awslambda.Permission(
    "EventsPermissionForLambda",
    Action="lambda:invokeFunction",
    FunctionName=Ref(lambda_function),
    Principal="events.amazonaws.com",
    SourceArn=GetAtt(schedule_event, "Arn")
))

print(template.to_json())
