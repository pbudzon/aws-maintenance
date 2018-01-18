from troposphere import Template, GetAtt, Join, Ref, Parameter, Equals, If, AWS_NO_VALUE, AWS_REGION
from troposphere import awslambda, iam, sns, rds
from awacs import aws, sts
import os

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
    Description="Optional: comma-delimited list of RDS instance names to use. Leave empty to use for all instances in source region."
))

template.add_condition("UseAllDatabases", Equals(Join("", Ref(databases_to_use_parameter)), ""))

template.add_metadata({
    "AWS::CloudFormation::Interface": {
        "ParameterGroups": [
            {
                "Label": {
                    "default": "Region configuration"
                },
                "Parameters": [
                    "TargetRegionParameter",
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
        ],
        "ParameterLabels": {
            "TargetRegionParameter": {"default": "Target region"},
            "DatabasesToUse": {"default": "Databases to use for"},
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
            )
        ])
    )]
))

# Lambda itself
source_file = os.path.realpath(__file__ + '/../../../backup-rds.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

if len(content) > 4096:
    raise Exception("Backup RDS function too long, has {}!".format(len(content)))

backup_rds_function = template.add_resource(awslambda.Function(
    'LambdaBackupRDSFunction',
    Description='Copies RDS backups to another region',
    Code=awslambda.Code(
        ZipFile=content
    ),
    Handler='index.lambda_handler',
    MemorySize=128,
    Role=GetAtt(backup_rds_role, 'Arn'),
    Runtime='python3.6',
    Timeout=10,
    Environment=awslambda.Environment(
        Variables={
            'SOURCE_REGION': Ref(AWS_REGION),
            'TARGET_REGION': Ref(target_region_parameter)
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

print(template.to_json())
