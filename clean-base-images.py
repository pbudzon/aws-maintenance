import boto3
import operator


def lambda_handler(event, context):
    LIMIT = 10
    client = boto3.client('ec2', 'eu-west-1')

    response = client.describe_images(
        Owners=['self'],
        Filters=[{'Name': 'tag:Type', 'Values': ['BaseImage']}]
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

    to_remove = []
    for project in images:
        sorted_x = sorted(images[project].items(), key=operator.itemgetter(1), reverse=True)
        if len(sorted_x) > LIMIT:
            to_remove = to_remove + [i[0] for i in sorted_x[LIMIT:]]

    if len(to_remove) == 0:
        print("Nothing to do")
        return 0

    print("Will remove " + str(len(to_remove)) + " images")

    for ami in to_remove:
        print("Removing: " + ami)
        client.deregister_image(ImageId=ami)


if __name__ == '__main__':
    lambda_handler(None, None)
