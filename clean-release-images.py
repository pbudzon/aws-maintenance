from __future__ import print_function
import boto3
import operator


def clean_images(region, limit):
    client = boto3.client('ec2', region)

    response = client.describe_images(
        Owners=['self'],
        Filters=[{'Name': 'tag:Type', 'Values': ['ReleaseImage']}]
    )

    if len(response['Images']) == 0:
        raise Exception('no AMIs with Type=BaseImage tag found')

    images = {}
    for image in response['Images']:
        for tag in image['Tags']:
            if tag['Key'] == "Project":
                if tag['Value'] not in images.keys():
                    images[tag['Value']] = {}
                images[tag['Value']][image['ImageId']] = image['CreationDate']
                break

    to_remove = [];
    for project in images:
        sorted_x = sorted(images[project].items(), key=operator.itemgetter(1), reverse=True)
        if len(sorted_x) > limit:
            to_remove = to_remove + [i[0] for i in sorted_x[limit:]]

    if len(to_remove) == 0:
        print("Nothing to do")
        return 0

    print("Will remove " + str(len(to_remove)) + " images")

    for ami in to_remove:
        print("Removing: " + ami)
        client.deregister_image(ImageId=ami)


def lambda_handler(event, context):
    clean_images('eu-west-1', 50)
    clean_images('eu-central-1', 1)


if __name__ == '__main__':
    lambda_handler(None, None)
