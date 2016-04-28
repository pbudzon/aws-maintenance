from troposphere import Template, GetAtt, Ref, Parameter
from troposphere.iam import Role
from troposphere.iam import Policy as IAMPolicy
from troposphere.awslambda import Function, Code
from troposphere.cloudwatch import Alarm, MetricDimension
from troposphere.sns import Subscription, Topic
from awacs.aws import Allow, Statement, Action, Principal, Policy
from awacs.sts import AssumeRole
import os

t = Template()

t.add_description('Stack with Lambda function performing maintenance tasks')

param_alarm_email = t.add_parameter(Parameter(
    "AlarmEmail",
    Description="Email where Lambda errors alarms should be sent to",
    Default="cnidevteam@condenastint.com",
    Type="String",
))

role = t.add_resource(Role(
    "LambdaCleanImagesRole",
    AssumeRolePolicyDocument=Policy(
        Statement=[
            Statement(
                Effect=Allow, Action=[AssumeRole],
                Principal=Principal(
                    "Service", ["lambda.amazonaws.com"]
                )
            )
        ]
    ),
    Policies=[IAMPolicy(
        "LambdaCleanBaseImagesPolicy",
        PolicyName="LambdaCleanBaseImagesPolicy",
        PolicyDocument=Policy(Statement=[
            Statement(
                Effect=Allow,
                Action=[
                    Action('ec2', 'DescribeImages'),
                    Action('ec2', 'DeregisterImage'),
                ],
                Resource=['*']
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('logs', 'CreateLogGroup'),
                    Action('logs', 'CreateLogStream'),
                    Action('logs', 'PutLogEvents'),
                ],
                Resource=['arn:aws:logs:*:*:*']
            )
        ])
    )]
))

backup_rds_role = t.add_resource(Role(
    "LambdaBackupRDSRole",
    AssumeRolePolicyDocument=Policy(
        Statement=[
            Statement(
                Effect=Allow, Action=[AssumeRole],
                Principal=Principal(
                    "Service", ["lambda.amazonaws.com"]
                )
            )
        ]
    ),
    Policies=[IAMPolicy(
        "LambdaBackupRDSPolicy",
        PolicyName="LambdaCleanBaseImagesPolicy",
        PolicyDocument=Policy(Statement=[
            Statement(
                Effect=Allow,
                Action=[
                    Action('rds', 'DescribeDbSnapshots'),
                    Action('rds', 'CopyDbSnapshot'),
                    Action('rds', 'DeleteDbSnapshot'),
                ],
                Resource=['*']
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('logs', 'CreateLogGroup'),
                    Action('logs', 'CreateLogStream'),
                    Action('logs', 'PutLogEvents'),
                ],
                Resource=['arn:aws:logs:*:*:*']
            )
        ])
    )]
))

source_file = os.path.realpath(__file__ + '/../../../clean-base-images.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

if len(content) > 4096:
    raise Exception("Base function too long!")

base_function = t.add_resource(Function(
    'LambdaBaseFunction',
    Description='Clears Base AMI images',
    Code=Code(
        ZipFile=content
    ),
    Handler='index.lambda_handler',
    MemorySize=128,
    Role=GetAtt(role, 'Arn'),
    Runtime='python2.7',
    Timeout=10
))

source_file = os.path.realpath(__file__ + '/../../../clean-release-images.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

if len(content) > 4096:
    raise Exception("Release function too long!")

release_function = t.add_resource(Function(
    'LambdaReleaseFunction',
    Description='Clears Release AMI images',
    Code=Code(
        ZipFile=content
    ),
    Handler='index.lambda_handler',
    MemorySize=128,
    Role=GetAtt(role, 'Arn'),
    Runtime='python2.7',
    Timeout=10
))

source_file = os.path.realpath(__file__ + '/../../../backup-rds.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

if len(content) > 4096:
    raise Exception("Backup RDS function too long!")

backup_rds_function = t.add_resource(Function(
    'LambdaBackupRDSFunction',
    Description='Copies RDS backups to Frankfurt (live only)',
    Code=Code(
        ZipFile=content
    ),
    Handler='index.lambda_handler',
    MemorySize=128,
    Role=GetAtt(backup_rds_role, 'Arn'),
    Runtime='python2.7',
    Timeout=10
))

alarm_topic = t.add_resource(Topic(
    'LambdaErrorTopic',
    Subscription=[Subscription(
        Protocol="email",
        Endpoint=Ref(param_alarm_email)
    )]
))

t.add_resource(Alarm(
    "LambdaBaseErrorsAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Errors',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(base_function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(alarm_topic)]
))

t.add_resource(Alarm(
    "LambdaReleaseErrorsAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Errors',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(release_function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(alarm_topic)]
))

t.add_resource(Alarm(
    "LambdaBackupRDSErrorsAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Errors',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(backup_rds_function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(alarm_topic)]
))

t.add_resource(Alarm(
    "LambdaBackupRDSThrottlesAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Throttles',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(backup_rds_function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(alarm_topic)]
))


print t.to_json()
