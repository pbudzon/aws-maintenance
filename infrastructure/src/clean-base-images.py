from troposphere import Template, GetAtt
from troposphere.iam import Role
from troposphere.iam import Policy as IAMPolicy
from troposphere.awslambda import Function, Code
from awacs.aws import Allow, Statement, Action, Principal, Policy
from awacs.sts import AssumeRole
import os

t = Template()

role = t.add_resource(Role(
    "LambdaCleanBaseImagesRole",
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

source_file = os.path.realpath(__file__ + '/../../../clean-base-images.py')
with open(source_file, 'r') as content_file:
    content = content_file.read()

t.add_resource(Function(
    'LambdaFunction',
    Code=Code(
        ZipFile=content
    ),
    Handler='lambda_handler.lambda_handler',
    MemorySize=128,
    Role=GetAtt(role, 'Arn'),
    Runtime='python2.7',
    Timeout=10
))

print t.to_json()
