from troposphere import Template, GetAtt, Ref, Parameter, Join, Output
from troposphere.iam import Role
from troposphere.iam import Policy as IAMPolicy
from troposphere.awslambda import Function, Code, Permission
from troposphere.sns import Subscription, Topic, TopicPolicy
from troposphere.cloudtrail import Trail
from troposphere.s3 import Bucket, BucketPolicy
from troposphere.cloudwatch import Alarm, MetricDimension
from awacs.aws import Allow, Statement, Action, Principal, Policy, Condition, StringEquals, ArnEquals
from awacs.sts import AssumeRole
import os

t = Template()

t.add_description('Lambda function monitoring cloudtrail logs')

notificationTopic = t.add_resource(Topic(
    "NotifcationTopic",
    DisplayName="CloudTrail Monitor Alerts"
))

bucket = t.add_resource(Bucket(
    "Bucket",
    AccessControl="Private",
    BucketName=Join("-", [Ref("AWS::StackName"), Ref("AWS::AccountId")]),
    DeletionPolicy="Retain"
))

bucket_policy = t.add_resource(BucketPolicy(
    "BucketPolicy",
    Bucket=Ref(bucket),
    PolicyDocument=Policy(
        Statement=[
            Statement(
                Sid="AWSCloudTrailAclCheck",
                Effect=Allow,
                Action=[Action("s3", "GetBucketAcl")],
                Principal=Principal(
                    "Service", ["cloudtrail.amazonaws.com"]
                ),
                Resource=[Join("", ["arn:aws:s3:::", Ref(bucket)])]
            ),
            Statement(
                Sid="AWSCloudTrailWrite",
                Effect=Allow,
                Action=[Action("s3", "PutObject")],
                Principal=Principal(
                    "Service", ["cloudtrail.amazonaws.com"]
                ),
                Resource=[Join("", ["arn:aws:s3:::", Ref(bucket), "/AWSLogs/", Ref("AWS::AccountId"), "/*"])],
                Condition=Condition(
                    StringEquals('s3:x-amz-acl', 'bucket-owner-full-control')
                )
            )
        ]
    )
))

lambda_role = t.add_resource(Role(
    "LambdaRole",
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
        "LambdaPolicy",
        PolicyName="LambdaCloudtrailPolicy",
        PolicyDocument=Policy(Statement=[
            Statement(
                Effect=Allow,
                Action=[
                    Action('s3', 'GetObject'),
                ],
                Resource=[Join("", ['arn:aws:s3:::', Ref(bucket), '/*'])]
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('logs', 'CreateLogGroup'),
                    Action('logs', 'CreateLogStream'),
                    Action('logs', 'PutLogEvents'),
                ],
                Resource=['arn:aws:logs:*:*:*']
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('lambda', 'GetFunction'),
                ],
                Resource=['*']  # todo: limit this to the function itself
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('sns', 'publish')
                ],
                Resource=[Ref(notificationTopic)]
            ),
            Statement(
                Effect=Allow,
                Action=[
                    Action('iam', 'ListRolePolicies'),
                    Action('iam', 'GetRolePolicy')
                ],
                Resource=['*']
            ),
        ])
    )]
))

source_file = os.path.realpath(__file__ + '/../../../cloudtrail-monitor.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

if len(content) > 4096:
    raise Exception("Function too long!")

function = t.add_resource(Function(
    'LambdaFunction',
    Description='Monitors CloudTrail',
    Code=Code(
        ZipFile=content
    ),
    Handler='index.lambda_handler',
    MemorySize=128,
    Role=GetAtt(lambda_role, 'Arn'),
    Runtime='python2.7',
    Timeout=10
))

cloudtrail_topic = t.add_resource(Topic(
    "CloudtrailTopic",
    Subscription=[
        Subscription(
            Endpoint=GetAtt(function, "Arn"),
            Protocol="lambda"
        )
    ]
))

lambda_permission = t.add_resource(Permission(
    "LambdaPermission",
    Action="lambda:InvokeFunction",
    FunctionName=Ref(function),
    Principal="sns.amazonaws.com",
    SourceAccount=Ref("AWS::AccountId"),
    SourceArn=Ref(cloudtrail_topic)
))

t.add_resource(TopicPolicy(
    "CloudtrailTopicPolicy",
    Topics=[Ref(cloudtrail_topic)],
    PolicyDocument=Policy(
        Statement=[
            Statement(
                Sid="AWSCloudTrailSNSPolicy",
                Effect=Allow,
                Principal=Principal(
                    "Service", ["cloudtrail.amazonaws.com"]
                ),
                Action=[Action("sns", "publish")],
                Resource=[Ref(cloudtrail_topic)]
            )
        ]
    )
))

cloudtrail = t.add_resource(Trail(
    "CloudTrail",
    IncludeGlobalServiceEvents=True,
    IsLogging=True,
    IsMultiRegionTrail=True,
    S3BucketName=Ref(bucket),
    SnsTopicName=Ref(cloudtrail_topic),
    DependsOn="BucketPolicy"
))

t.add_resource(Alarm(
    "LambdaErrorsAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Errors',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(notificationTopic)]
))

t.add_resource(Alarm(
    "LambdaThrottlesAlarm",
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Throttles',
    Namespace='AWS/Lambda',
    Dimensions=[
        MetricDimension(
            Name='FunctionName',
            Value=Ref(function)
        )
    ],
    Period=300,
    Statistic='Maximum',
    Threshold='0',
    AlarmActions=[Ref(notificationTopic)]
))


t.add_output(Output(
    "SNSNotificationTopic",
    Description="SNS topic to which the alerts will be send",
    Value=Ref(notificationTopic)
))

print t.to_json()
