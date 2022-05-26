# [Whisper](https://github.com/viyh/whisper) #

Whisper is used to simply and securely distribute secrets that are too
sensitive to send via plaintext.

## Overview ##

![Whisper Architecture](whisper_arch.png?raw=true "Architecture")

How it works:

A user has a secret to send to someone else. Instead of using insecure means
such as email or instant messenger, they enter the secret and a password used to
encrypt the secret. The secret can be text or a file and an expiration time is
chosen for the secret such as one time, hour, day, or week. The user receives a
link from the server which can be shared with the other person as well as the
shared password used for retrieval. The password should be shared separately
from the link, such as sending the link by email and telling them the password
via txt message. The other person can retrieve the secret by browsing to the
link and entering the shared password.

All AES encryption and decryption is handled on the client-side, so no data is
transmitted in plaintext. The backend stores the encrypted data and salted
password hash, but because the client creates a salted SHA512 hash from the
password before sending it to the server, even if the server is compromised or
the administrator is a malicious actor, they will be unable to decrypt the
secret data.

## Installation ##

### Docker ###

The Docker image is available on Dockerhub:

[https://hub.docker.com/r/viyh/whisper/](https://hub.docker.com/r/viyh/whisper/)

Run the docker image:

        docker run --name whisper \
            -p 8000:8000 \
            -e SECRET_KEY=thi\$1smyC00L5ecr3t \
            -it viyh/whisper:0.1.0

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

Joe Richards (@viyh)

## Licence ##

[MIT License](LICENSE)
