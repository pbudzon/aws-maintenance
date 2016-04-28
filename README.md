# aws-maintenance
Collection of scripts and lambda functions used for maintaining AWS

## backup-rds.py

Lambda function used to copy RDS snapshot from eu-west-1 (Ireland) to eu-central-1 (Frankfurt). One (latest) copy for each RDS instance is kept in Frankfurt.

## clean-base-images.py and clean-release-images.py

Remove AMIs from eu-west-1 (Ireland) to eu-central-1 (Frankfurt) based on different tags.

Meant to be used as a part of immutable infrastructure, where each project has a base AMI (tagged with `Type=BaseImage`) and
each release in contained within a new AMI based on it (tagged with `Type=ReleaseImage`). 

Assumptions: 

1. base images are stored in Ireland. Release images are stored in Ireland and Frankfurt (as backups).
1. Apart from `Type` tag, each AMI has a `Project` tag, which can contain any value.

Those scripts make sure only a certain amount of recent images for each project is stored to limit the costs.

## clean-es-indices.py

Removes old CloudWatch indices inside AWS ElasticSearch Service. Useful when using CloudWatch log streaming into ElasticSearch.

Configure list of accounts, ElasticSearch endpoint and amount of last indices to be kept inside the code.