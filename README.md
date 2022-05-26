# [Whisper](https://github.com/viyh/whisper) #

Whisper provides a simple way to share secret information with someone else,
such as passwords, credentials, keys, or other sensitive data.

## Overview ##

![Whisper Architecture](docs/whisper_arch.png?raw=true "Architecture")

How it works:

A user has a secret to send to someone else. Instead of using insecure means
such as email or instant messenger, they enter the secret text or file along with
a password used to encrypt the secret. The secret can be text or a file and an
expiration time is chosen for the secret such as one time, hour, day, or week.
The user receives a link from the server which can be shared with the other
person as well as the shared password used for retrieval. The password should
be shared separately from the link, such as sending the link by email and
telling them the password via txt message. The other person can retrieve the
secret by browsing to the link and entering the shared password.

All AES encryption and decryption is handled on the client-side, so no data is
transmitted in plaintext. The backend stores the encrypted data and salted
password hash, but because the client creates a salted SHA512 hash from the
password before sending it to the server, even if the server is compromised or
the administrator is a malicious actor, they will be unable to decrypt the
secret data.

### Crypto ###

The secret text/file is encrypted using AES on the client-side and a
user-supplied password. Only after encryption is the data transmitted to the
server for storage. The secret password is also hashed (salted SHA512 with 10000
rounds) before being sent, in order to protect against eavesdropping, server
compromise, or malicious server administrators. The data is stored in the server
storage backend and the password is re-hashed along with a server-specific key
using bcrypt before also being stored in the backend. This protects the key
further from being cracked or stolen and resent to retrieve the encrypted
secret.

To retrieve a secret, the client-hashed password is sent to the server where it
is hashed using the server-key and compared against the stored hash. If they
match, the server sends the encrypted secret data back to the client. The client
then decrypts the data using the password.

### Frontend ###

Nginx is used as the front end. The configuration is stored at
/tmp/nginx.template.conf and envsubst is used at runtime to replace the WEB_PORT
variable.

### App ###

The Flask app is contained withint the app.py file. This deals with firing up
the Flask application, parsing the config file, the endpoint code, and
initializing the storage backend.

### Storage Backend ###

### Secrets ###

### Stores ###

### Store Cleaner ###

Whisper has a storage cleaner which will delete secrets which have expired. The
storage cleaner runs at intervals of your choosing for the granularity of
secrecy you require.

For instance, if a secret is created with an expiration period of "1 day", the
expiratiion date is timestamped down to the second. If the storage cleaner
period is set to "900" seconds (the default) in the configuration file, then
that secret may exist for up to 14 minutes and 59 seconds after it truly
expired, and then the storage cleaner will actually remove it from the storage
backend. This can be tuned to a lower setting if needed, but keep in mind that
the more frequently that the cleaner runs, the more resources such as disk IO,
network bandwidth, etc. it will use depending upon the specifics of the storage
backend. For these reasons, it's usually sufficient to keep the cleaner run
interval set to the default of 900 seconds (15 minutes) since this consumes
minimal resources and is typically an acceptible additional potential wait
period before deletion.

### Configuration ###


## Installation ##

Whisper is meant to be run as a Docker container so this documentation assumes
that. It can certainly be run outside of Docker, however that is left up as an
exercise to the reader because there are many advantages to running as a simple
container.

The installation process depends upon a few things:

* configuration file
* storage backend
* credentials for access to the storage backend (if necessary)

### Configuration File ###

The configuration file allows the customization of many runtime parameters,
including most importantly the server secret key, and the storage backend.

The code repository contains a config.default.yaml that can be copied and used
as a starting point. Your configuration file will need to be mounted into the
container to /usr/src/app/config.yaml. All examples of running Whisper below
include this. Do not mount over the top of the config.default.yaml or the
application may not work correctly.

The server secret key is used for encrypting the secret password as an extra
layer of protection. If the storage backend is compromised and the stored
secrets are stolen, the password hashes cannot be decrypted without the server
secret key. This also means that if a secret is created and then the server
secret key is changed, the secret cannot be decrypted.

The other important part of the configuration is selecting a storage backend.
There are four options provided: local disk, in-memory, AWS S3, and GCP Cloud
Storage (GCS). A custom storage backend can also be written and used. Each store
has a different set of configuration options which are outlined in detail within
their section of the documentation below.

### Storage Backend ###

A storage backend is used to store the secrets.

#### Local Disk ####

Local disk is the default mode of storage. Whisper will store secrets within the
container in the /tmp/whisper path, so any volume mounted at that location will
persist. If no volume is mounted, the secrets will not perist between application
runs. Other than a volume mount, no other external dependencies are required, so
this is a great way to get started if you want persistent data.

An example command to get started assuming that you have a storage directory of
/home/whisper on your host machine would be:

    docker run -it --rm --name whisper -p 8000:8000 \
        -v /home/whisper/config.yaml:/usr/src/app/config.yaml \
        -v /home/whisper/data:/tmp/whisper \
        viyh/whisper:0.1.0

#### In-Memory Storage ####

In-memory storage is the simplest storage method and most secure, however it
will not persist any data between application runs, so all secrets will be lost
once the application stops. Since the typical usage of Whisper is ephemeral
secrets being sent quickly between collegues, this may be sufficient and a
tolerable loss with the added benefit of simplicity of setup.

Within the configuration file, make sure any other storage backends are
commented out, and then make sure to uncomment the section for the in-memory
store backend. An example command to run Whisper would look something like this,
assuming that the configuration file is stored at /home/whisper/config.yaml on
the local host:

    docker run -it --rm --name whisper -p 8000:8000 \
        -v /home/whisper/config.yaml:/usr/src/app/config.yaml \
        viyh/whisper:0.1.0

#### AWS S3 Storage ####

Cloud storage such as S3 is a fairly straigh-forward switch to make for any
application that requires persistent storage and also wants to gain the ability
to become scalable. However, the one additional caveat to cloud storage is that
there may be an additional cost to both store the data (very minimal) and
retreive the data. Whisper has a storage cleaner


#### GCP GCS Storage ####

### Credentials ###

#### AWS ####

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

### Docker ###

The Docker image is available on Dockerhub:

[https://hub.docker.com/r/viyh/whisper/](https://hub.docker.com/r/viyh/whisper/)

Run the docker image:

        docker run --rm --name whisper \
            -p 8001:8000 \
            -e SECRET_KEY=thisISmyC00L5ecr3t \
            -it viyh/whisper:0.1.0-alpha

## Dependencies ##

* [Flask](https://flask.palletsprojects.com/en/2.1.x/)
* [Boto3](https://aws.amazon.com/sdk-for-python/)
* [Google Cloud Storage](https://googleapis.dev/python/storage/latest/index.html)
* [CryptoJS](https://github.com/brix/crypto-js)
* [clipboard.js](https://clipboardjs.com/)

## Development ##

### Writing Storage Backends ###

See src/whisper/storage/__init__.py for code and class implementation.

If implementing a custom storage backend, the cleaner thread calls a store
class's "delete_expired()" method. A store class should override this method and
provide any functionality necessary to delete any secrets that return True with
the "secret.check_id()" and return True from the "secret.is_expired()" secret
class methods. All other objects should remain untouched. "Is it really a secret
and is it expired?"

### Building ###

### Contributing ###

## Author ##

Joe Richards (GitHub: [@viyh](https://github.com/viyh))

## Licence ##

[MIT License](LICENSE)
