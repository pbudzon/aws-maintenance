# aws-maintenance
Collection of scripts and Lambda functions used for maintaining various AWS resources.

## Cross-region RDS backups (backup-rds.py)

Lambda function used to copy RDS snapshot from one region to another, to allow for the database to be restored in case 
of region failure.
One (latest) copy for each RDS instance is kept in the target region.

Use `infrastructure/templates/rds-cross-region-backup.json` CloudFormation template to create the Lambda and all 
resources it needs. It will create a subscription from RDS to Lambda, whenever an automated RDS snapshot on any database
 in that AWS region is made - that snapshot will be copied to target region and all older snapshots for that database 
 will be removed.

### Regions 
You will be asked to specify the target region to use by Lambda when creating the CloudFormation stack. The stack needs
to be created in the same region where the RDS databases that you want to use it for are located.

### Limit to specific RDS instances
You can also limit the function to only act for specific databases - specify the list of names in the "Databases to use 
for" parameter when creating the CloudFormation stack. If you leave it empty, Lambda will trigger for all RDS instances 
within the source region.

### Encryption
If your RDS instances are encrypted, you need to provide a KMS key ARN in the target region when creating the stack.

Since KMS keys are region-specific, when the snapshot is copied into another region, it needs to be re-encrypted
using a key located in that region. 
[Create a KMS key](https://docs.aws.amazon.com/kms/latest/developerguide/create-keys.html#create-keys-console) in the 
target region, copy its ARN and paste that value into `KMS Key in target region` parameter when creating the 
CloudFormation stack. **If you do not provide that value, copy operation for encrypted snapshots will fail.**

You can also provide that value if your RDS instances are not encrypted - the copied snapshots will be encrypted using 
that key. 

If you don't use encryption and don't want your snapshots to be encrypted, leave the `KMS Key in target region` 
parameter empty.


## Monitor CloudTrail events (cloudtrail-monitor.py)

Lambda function which monitors CloudTrail logs and sends SNS notification on `LaunchInstances` event. 
This can be modified to look for and respond to any AWS API calls as needed.

Use `infrastructure/templates/cloudtrail-notifications.json` CloudFormation template to create the Lambda,
 CloudTrail and SNS topics. In the Outputs of the CloudFormation
stack, you'll find the SNS topic to which you can subscribe to receive the notifications.


## Other Lambdas

The Lambdas below can be created by using `infrastructure/templates/maintenance-lambdas.json` CloudFormation template.

You should probably review (and adjust) them to your needs as necessary. They are provided as examples.

### clean-base-images.py and clean-release-images.py

Remove AMIs from eu-west-1 (Ireland) to eu-central-1 (Frankfurt) based on different tags.

Meant to be used as a part of immutable infrastructure, where each project has a base AMI (tagged with `Type=BaseImage`) 
and each release in contained within a new AMI based on it (tagged with `Type=ReleaseImage`). 

Assumptions: 

1. base images are stored in Ireland. Release images are stored in Ireland and Frankfurt (as backups).
1. Apart from `Type` tag, each AMI has a `Project` tag, which can contain any value.

Those scripts make sure only a certain amount of recent images for each project is stored to limit the costs.

### clean-es-indices.py

Removes old CloudWatch indices inside AWS ElasticSearch Service. Useful when using CloudWatch log streaming into 
ElasticSearch.

Configure list of accounts, ElasticSearch endpoint and amount of last indices to be kept inside the code.