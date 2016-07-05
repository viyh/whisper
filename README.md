# [Whisper](https://github.com/viyh/whisper) #

Whisper is used to securely distribute credentials that are too sensitive to send via plaintext.

## Overview ##

The data is entered and encryted with AES using a supplied password. A link is
created and can be sent to the other party, and the password can be provided to
them by other means such as instant messaging or a phone call. The data can be
set to delete after one viewing, one hour, one day, or one week. Any data will
be deleted at a maximum of 30 days regardless of if it was retrieved. DynamoDB
is used to store the data.

All encryption is done client-side, so no data is transmitted in plaintext. The
only data stored in the DynamoDB table is the encrypted text, salted SHA256 hash,
ID number, and date of expiration and creation.

## Installation ##


### Docker ###

The Docker image is available on Dockerhub:

[https://hub.docker.com/r/viyh/whisper/](https://hub.docker.com/r/viyh/whisper/)

Run the docker image:

        docker run --name whisper \
            -p 8000:8000 \
            -e SECRET_KEY=thi\$1smyC00L5ecr3t \
            -it viyh/whisper

### DynamoDB Table ###

Create a DynamoDB table with a primary key of "id" (string). By default, this table should be named "whisper" but can be renamed if the `DYNAMO_TABLENAME` is set.

### AWS Credentials ###

Setup an AWS user with read/write access to the DynamoDB table. The following
policy can be used to create the least permissions necessary:

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:BatchGetItem",
                "dynamodb:BatchWriteItem",
                "dynamodb:DeleteItem",
                "dynamodb:DescribeTable",
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:UpdateItem"
            ],
            "Resource": [
                "arn:aws:dynamodb:us-east-1:123456789012:table/whisper"
            ]
        }
    ]
}
```

The AWS credentials with access to the DynamoDB table can be supplied by either
binding a ".aws" directory to "/root/.aws" or by setting the appropriate
environment variables below.

For example:

        docker run --name whisper -p 8000:8000 -v $(pwd):/root/.aws -it viyh/whisper

Or with environment variables:

        docker run --name whisper -p 8000:8000 \
            -e AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION=us-east-1 \
            -e SECRET_KEY=thi\$1smyC00L5ecr3t \
            -it viyh/whisper


### Environment Variables ###

Any of these defaults can be overridden when running the Docker container.

* WEB_URL - Default: http://localhost:8000 - The URL that links use.
* WEB_PORT - Default: 8000 - The port for the WSGI service.
* SECRET_KEY - Default: random, you should set this. - The secret key used when salting the password hashes specific to this container.
* DYNAMO_TABLENAME - Default: whisper - The name of the DynamoDB table.
* AWS_ACCESS_KEY_ID - Default (none) - The access key for AWS access.
* AWS_SECRET_ACCESS_KEY - Default (none) - The secret key for AWS access.
* AWS_DEFAULT_REGION - Default: (none) - The region with the DynamoDB table.
* DEBUG - Default: False - Turn on debugging.

## Usage ##

Browse to the WEB_URL, such as [http://localhost:8000](http://localhost:8000) by default.

Enter the text data to be secured and a password used to encrypt it. After the
"Get link" button is clicked, a URL is created which can be sent via any plaintext
method. The password can also be given to the recipient but should be transimitted
via a different means, such as on the phone or instant message.

The recipient can browse to the link and enter the password to retrieve the text data.

## Dependencies ##

* [Flask](http://flask.pocoo.org/)
* [Boto3](http://aws.amazon.com/sdk-for-python/)
* [CryptoJS](https://github.com/brix/crypto-js)
* [clipboard.js](https://clipboardjs.com/)

## Author ##

Joe Richards <nospam-github@disconformity.net>

## Licence ##

[MIT License](LICENSE)
