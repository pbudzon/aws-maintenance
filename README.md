# aws-maintenance
Collection of scripts and Lambda functions used for maintaining various AWS resources.

## Cross-region RDS backups (backup-rds.py)

Lambda function used to copy RDS snapshot from one region to another, to allow for the database to be restored in case 
of region failure. One (latest) copy for each RDS instance is kept in the target region. The provided CloudFormation
 template will create a subscription from RDS to Lambda, whenever an automated RDS snapshot on any database
 in that AWS region is made - that snapshot will be copied to target region and all older snapshots for that database 
 will be removed.

### Regions 
You will be asked to specify the target region (where to copy your snapshots) to use by Lambda when creating the 
CloudFormation stack. The stack itself needs to be created in the same region where the RDS databases that you want to
 use it for are located.

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

### Aurora clusters
Since Aurora clusters do not offer an event notification for their automated backups, a daily schedule needs to be used
to copy the latest snapshot over to the target region. If you're using clusters, set `Use for Aurora clusters` to 'Yes'
when creating the CloudFormation stack. You can limit which clusters' snapshots are copied by specifying a comma-delimited 
list in `Aurora clusters to use for` parameter.
The snapshots will be copied over once a day, at a random time of AWS choosing (using CloudWatch Event with `rate(1 day)`).

### Guide

#### How to use for the first time
1. Download the [backup-rds.py](https://raw.githubusercontent.com/pbudzon/aws-maintenance/master/backup-rds.py) file
 from this repository and zip it into a file called `backup-rds.zip` (for example: `zip backup-rds.zip backup-rds.py`).
1. Upload the ZIP file to an S3 bucket on your AWS account in the same region where your RDS instances live.
1. Create a new CloudFormation stack using the template: `infrastructure/templates/rds-cross-region-backup.json`.
1. CloudFormation will ask you for the following parameters:
    - Required: **Target region** - provide the id of the AWS region where the copied snapshots should be stored, like
     'eu-central-1'. Those are listed in
      [AWS documentation](https://docs.aws.amazon.com/general/latest/gr/rande.html#rds_region).
    - Required: **Name of S3 bucket** - name of the S3 bucket where you uploaded the ZIP in earlier step.
    - Required: **Name of ZIP file** - name of the ZIP file in S3 bucket you uploaded. If you uploaded it into a directory,
    provide a path to the file in S3 (for example `lambda_code/backup-rds.zip`)
    - Required/Optional: **KMS Key in target region** - if your RDS instances are encrypted, provide an ARN of a KMS key
     in the target region. See Encryption section above. 
    - Optional: **Databases to use for** - if you want limit the functionality to only specific RDS instances, provide 
    a comma-delimited list of their names.
    - Optional: **Use for Aurora clusters** - select "Yes" if you have any Aurora Clusters that you want this code to work
    with.
    - Optional: **Aurora clusters to use for** (applies only if you select "Yes" above) - if you want to limit the 
    functionality to only specific Aurora Clusters, provide a comma-delimited list of clusters names.

#### How to update to the latest version
Follow the update steps, but name the zip file something else that before - for example, if you uploaded `backup-rds.zip`,
upload the new file as `backup-rds-1.zip`. Update your CloudFormation stack with the latest template from this repo, 
and provide that new ZIP file name in *Name of ZIP file* parameter. 

#### How to test
Once all resources are created, you can test your Lambda from the Console, by using the following test event:
```
{
  "Records": [
    {
      "EventVersion": "1.0",
      "EventSubscriptionArn": "arn:aws:sns:EXAMPLE",
      "EventSource": "aws:sns",
      "Sns": {
        "Type": "Notification",
        "MessageId": "abcd",
        "TopicArn": "arn:aws:sns:eu-west-1:123456789012:topic_name",
        "Subject": "RDS Notification Message",
        "Message": "{\"Event Source\":\"db-instance\",\"Event Time\":\"2017-12-26 22:34:07.882\",\"Identifier Link\":\"https://console.aws.amazon.com/rds/home?region=eu-west-1#dbinstance:id=database_name\",\"Source ID\":\"PUT_YOUR_RDS_NAME_HERE\",\"Event ID\":\"http://docs.amazonwebservices.com/AmazonRDS/latest/UserGuide/USER_Events.html#RDS-EVENT-0002\",\"Event Message\":\"Finished DB Instance backup\"}",
        "Timestamp": "2017-12-26T22:35:19.946Z",
        "SignatureVersion": "1",
        "Signature": "xxx",
        "SigningCertURL": "xxx",
        "UnsubscribeURL": "xxx"
      }
    }
  ]
}
```
Replace the `PUT_YOUR_RDS_NAME_HERE` in the JSON string with a name of any of your RDS instances. 

For Aurora Clusters, use the below event (no need to change anything):
```
{
  "version": "0",
  "id": "eb6d8ba9-c5c2-3269-3ac4-9918a9df74d9",
  "detail-type": "Scheduled Event",
  "source": "aws.events",
  "account": "123456789012",
  "time": "2018-01-30T21:11:00Z",
  "region": "eu-west-1",
  "resources": [
    "arn:aws:events:eu-west-1:123456789012:rule/eventName"
  ],
  "detail": {}
}
```
The code will go through all clusters (or those listed in *Aurora clusters to use for* parameter).


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