from awacs import aws, sts
from troposphere import Template, GetAtt, Join, Ref, Parameter, Equals, If, AWS_NO_VALUE, AWS_REGION
from troposphere import awslambda, iam, sns, rds, events

template = Template()

template.add_description('Resources copying RDS backups to another region')

target_region_parameter = template.add_parameter(Parameter(
    "TargetRegionParameter",
    Type="String",
    Description="Region where to store the copies of snapshots (for example: eu-central-1)",
    AllowedPattern="^[a-z]+-[a-z]+-[0-9]+$",
    ConstraintDescription="The target region needs to be valid AWS region, for example: us-east-1"
))

databases_to_use_parameter = template.add_parameter(Parameter(
    "DatabasesToUse",
    Type="CommaDelimitedList",
    Description="Optional: comma-delimited list of RDS instance (not Aurora clusters!) names to use. Leave empty to use for all instances in source region."
))

include_aurora_clusters_parameter = template.add_parameter(Parameter(
    "IncludeAuroraClusters",
    Type="String",
    AllowedValues=["Yes", "No"],
    Default="No",
    Description="Choose 'Yes' if you have Aurora Clusters that you want to use this for, will add daily schedule."
))

clusters_to_use_parameter = template.add_parameter(Parameter(
    "ClustersToUse",
    Type="String",
    Default="",
    Description="Optional: If including Aurora clusters - comma-delimited list of Aurora Clusters to use for. Leave empty to use for all clusters in source region."
))

kms_key_parameter = template.add_parameter(Parameter(
    "KMSKeyParameter",
    Type="String",
    Description="KMS Key ARN in target region. Required if using encrypted RDS instances, optional otherwise.",
))

s3_bucket_parameter = template.add_parameter(Parameter(
    "S3BucketParameter",
    Type="String",
    Description="Name of the S3 bucket where you uploaded the source code zip",
))

source_zip_parameter = template.add_parameter(Parameter(
    "SourceZipParameter",
    Type="String",
    Default="backup-rds.zip",
    Description="Name of the zip file inside the S3 bucket",
))


template.add_condition("UseAllDatabases", Equals(Join("", Ref(databases_to_use_parameter)), ""))
template.add_condition("UseEncryption", Equals(Ref(kms_key_parameter), ""), )
template.add_condition("IncludeAurora", Equals(Ref(include_aurora_clusters_parameter), "Yes"))

template.add_metadata({
    "AWS::CloudFormation::Interface": {
        "ParameterGroups": [
            {
                "Label": {
                    "default": "Basic configuration"
                },
                "Parameters": [
                    "TargetRegionParameter",
                    "S3BucketParameter",
                    "SourceZipParameter",
                ]
            },
            {
                "Label": {
                    "default": "Encryption - see https://github.com/pbudzon/aws-maintenance#encryption for details"
                },
                "Parameters": [
                    "KMSKeyParameter",
                ]
            },
            {
                "Label": {
                    "default": "Optional: limit to specific RDS database(s)"
                },
                "Parameters": [
                    "DatabasesToUse",
                ]
            },
            {
                "Label": {
                    "default": "Optional: Aurora support"
                },
                "Parameters": [
                    "IncludeAuroraClusters",
                    "ClustersToUse"
                ]
            },
        ],
        "ParameterLabels": {
            "TargetRegionParameter": {"default": "Target region"},
            "DatabasesToUse": {"default": "Databases to use for"},
            "KMSKeyParameter": {"default": "KMS Key in target region"},
            "IncludeAuroraClusters": {"default": "Use for Aurora clusters"},
            "ClustersToUse": {"default": "Aurora clusters to use for"},
            "S3BucketParameter": {"default": "Name of S3 bucket"},
            "SourceZipParameter": {"default": "Name of ZIP file"},
        }
    }
})

# Role for Lambda
backup_rds_role = template.add_resource(iam.Role(
    "LambdaBackupRDSRole",
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
        PolicyName="AccessToRDSAndLogs",
        PolicyDocument=aws.Policy(Statement=[
            aws.Statement(
                Effect=aws.Allow,
                Action=[
                    aws.Action('rds', 'DescribeDbSnapshots'),
                    aws.Action('rds', 'CopyDbSnapshot'),
                    aws.Action('rds', 'DeleteDbSnapshot'),
                    aws.Action('rds', 'DeleteDbClusterSnapshot'),
                    aws.Action('rds', 'DescribeDbClusters'),
                    aws.Action('rds', 'DescribeDbClusterSnapshots'),
                    aws.Action('rds', 'CopyDBClusterSnapshot'),
                ],
                Resource=['*']
            ),
            aws.Statement(
                Effect=aws.Allow,
                Action=[
                    aws.Action('logs', 'CreateLogGroup'),
                    aws.Action('logs', 'CreateLogStream'),
                    aws.Action('logs', 'PutLogEvents'),
                ],
                Resource=['arn:aws:logs:*:*:*']
            ),
            If(
                "UseEncryption",
                Ref(AWS_NO_VALUE),
                aws.Statement(
                    Effect=aws.Allow,
                    Action=[
                        aws.Action('kms', 'Create*'),  # Don't ask me why this is needed...
                        aws.Action('kms', 'DescribeKey'),
                    ],
                    Resource=[Ref(kms_key_parameter)]
                ),
            ),
        ])
    )]
))

backup_rds_function = template.add_resource(awslambda.Function(
    'LambdaBackupRDSFunction',
    Description='Copies RDS backups to another region',
    Code=awslambda.Code(
        S3Bucket=Ref(s3_bucket_parameter),
        S3Key=Ref(source_zip_parameter),
    ),
    Handler='backup-rds.lambda_handler',
    MemorySize=128,
    Role=GetAtt(backup_rds_role, 'Arn'),
    Runtime='python3.6',
    Timeout=30,
    Environment=awslambda.Environment(
        Variables={
            'SOURCE_REGION': Ref(AWS_REGION),
            'TARGET_REGION': Ref(target_region_parameter),
            'KMS_KEY_ID': Ref(kms_key_parameter),
            'CLUSTERS_TO_USE': Ref(clusters_to_use_parameter)
        }
    )
))

# SNS topic for event subscriptions
rds_topic = template.add_resource(sns.Topic(
    'RDSBackupTopic',
    Subscription=[sns.Subscription(
        Protocol="lambda",
        Endpoint=GetAtt(backup_rds_function, 'Arn'),
    )]
))

# Event subscription - RDS will notify SNS when backup is started and finished
template.add_resource(rds.EventSubscription(
    "RDSBackupEvent",
    Enabled=True,
    EventCategories=["backup"],
    SourceType="db-instance",
    SnsTopicArn=Ref(rds_topic),
    SourceIds=If("UseAllDatabases", Ref(AWS_NO_VALUE), Ref(databases_to_use_parameter))
))

# Permission for SNS to trigger the Lambda
template.add_resource(awslambda.Permission(
    "SNSPermissionForLambda",
    Action="lambda:invokeFunction",
    FunctionName=Ref(backup_rds_function),
    Principal="sns.amazonaws.com",
    SourceArn=Ref(rds_topic)
))

schedule_event = template.add_resource(events.Rule(
    "AuroraBackupEvent",
    Condition="IncludeAurora",
    Description="Copy Aurora clusters to another region",
    ScheduleExpression="rate(1 day)",
    State="ENABLED",
    Targets=[
        events.Target(
            Arn=GetAtt(backup_rds_function, "Arn"),
            Id="backup_rds_function"
        )
    ]
))

# Permission for CloudWatch Events to trigger the Lambda
template.add_resource(awslambda.Permission(
    "EventsPermissionForLambda",
    Condition="IncludeAurora",
    Action="lambda:invokeFunction",
    FunctionName=Ref(backup_rds_function),
    Principal="events.amazonaws.com",
    SourceArn=GetAtt(schedule_event, "Arn")
))

print(template.to_json())
