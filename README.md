# [Whisper](https://github.com/viyh/whisper) #

Whisper provides a simple way to share secret information with someone else,
such as passwords, credentials, keys, or other sensitive data.

## Quick Start ##

To get up and running:

* Copy the [default config file](src/config.default.yaml) to config.yaml
* Set the secret_key
* Create a volume (optional, if persistent disk storage is needed)
* Set up cloud credentials (required only if a cloud storage backend is used)
* Run the container

### Create a configuration file ###

Copy the [default config file](src/config.default.yaml) to a new config.yaml as
a starting point.

Change the storage backend settings if needed, by default it will use local disk
storage so you will need to mount a volume path when you run the container if
you want secrets to persist.

### Set the secret_key ###

At a minimum, set the secret_key to a random string. A simple way to generate a
secret key is by running the following command:

    head /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32 && echo

Save the output as the "secret_key" configuration parameter in the new
config.yaml file.

### Create a volume (optional) ###

If using memory, S3, or GCS, no persistent storage is needed. If using local
disk storage, then a volume will need to be created and mounted to persist data
between application executions.

To create a docker volume:

    docker volume create whisper-storage

### Set up credentials ###

If using S3 or GCS, credentials are needed in order to access the backend. Each
of these providers has multiple ways of automatically providing credentials to
the backend.

#### S3 ####

With any of the following three methods to provide credentials to the
application, a minimum set of IAM permissions will need to be granted to that
user/role.

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetBucketLocation",
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:GetObjectTagging",
                "s3:PutObjectTagging",
                "s3:DeleteObjectTagging",
            ],
            "Resource": [
                "arn:aws:s3:::my-whisper-bucket",
                "arn:aws:s3:::my-whisper-bucket/*"
            ]
        }
    ]
}
```

##### IAM Role #####

The simplest way is to use the built-in IAM roles to provide access. The code
will automatically use the IAM role to access the backend, so no additional
configuration is needed with this method.

##### Credential File #####

A second method is to mount a ".aws/" directory containing the config and/or
credentials file into the container. If using a specific profile, the env var
AWS_PROFILE can be set to specify which profile should be used.

These can be specified in the Docker run command, such as:

    docker run -it --rm --name whisper -p 8000:8000 \
        -v /home/whisper/config.yaml:/usr/src/app/config.yaml \
        -v ~/.aws:/.aws:ro \
        -e AWS_PROFILE=default \
        viyh/whisper:0.1.0

More info can be found [here.](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)

##### Env Vars #####

The final method that can be used is setting the environment variables for the
AWS access key ID and secret access key. The env vars are:

* AWS_ACCESS_KEY_ID
* AWS_SECRET_ACCESS_KEY
* AWS_DEFAULT_REGION

These can be specified in the Docker run command, such as:

    docker run -it --rm --name whisper -p 8000:8000 \
        -v /home/whisper/config.yaml:/usr/src/app/config.yaml \
        -e AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE \
        -e AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY \
        -e AWS_DEFAULT_REGION=us-east-1 \
        viyh/whisper:0.1.0

See also the [AWS documentation for environment variables.](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html)

### Run the container ###

After the above steps, the container can be run:

    docker run -it --rm --name whisper -p 8000:8000 \
        -v /home/whisper/config.yaml:/usr/src/app/config.yaml \
        -v whisper-storage:/tmp/whisper \
        viyh/whisper:0.1.0

Once it is running, you can use Whisper by browsing to: http://localhost:8000

## Overview ##

![Whisper Architecture](docs/whisper_arch.png?raw=true "Architecture")

How it works:

A user has a secret to send to someone else. Instead of using insecure means
such as email or instant messenger, they enter the secret text or file along
with a password used to encrypt the secret. The secret can be text or a file and
an expiration time is chosen for the secret such as one time, hour, day, or
week. The user receives a link from the server which can be shared with the
other person as well as the shared password used for retrieval. The password
should be shared separately from the link, such as sending the link by email and
telling them the password via txt message. The other person can retrieve the
secret by browsing to the link and entering the shared password.

All AES encryption and decryption is handled on the client-side, so no data is
transmitted in plaintext. The backend stores the encrypted data and salted
password hash, but because the client creates a salted SHA512 hash from the
password before sending it to the server, even if the server is compromised or
the administrator is a malicious actor, they will be unable to decrypt the
secret data.

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

### Crypto ###

The secret text/file is encrypted using AES on the client-side and a
user-supplied password. The data is only transmitted after encryption to the
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

Nginx is used as the front end webserver. The configuration is stored within the
container at /tmp/nginx.template.conf and envsubst is used at runtime to replace
the WEB_PORT environment variable.

The Flask app is contained withint the app.py file. This deals with firing up
the Flask application, parsing the config file, the endpoint code, and
initializing the storage backend.

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

The default storage backend is local disk. Whisper will store secrets within the
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
retreive the data. Whisper has a storage cleaner which periodically checks for
expired secrets. To accomplish this with S3 without having to pull the entire
secret which could lead to high costs for retrieving the data if many and/or
large secrets are stored, S3 tags are used to tag each object stored with the
creation (tag: create_date) and expiration dates (tag: expire_date). This allows
the storage cleaner to pull only the tags for each object making it a simple,
small request. If the object is determined to be expired based on the values of
these tags, then the object is deleted.

#### GCP Google Cloud Storage ####

Similar to S3 storage, GCS can be used to make the application more scalable by
detaching the need for local storage but providing persistence and the ability
for multiple instances of the application to access the stored secrets.

GCS allows metadata stored with each object (similar to S3 tags), so metadata
keys for "expire_date" and "create_date" are added so that the entire object
does not need to be pulled in order to expire secrets by the store cleaner.

### Environment Variables ###

Any of these defaults can be overridden when running the Docker container.

* WEB_PORT - Default: 8000 - The port for Whisper to listen on.
* LOG_LEVEL - Default: INFO - Debugging can be turned on by setting this to "DEBUG".

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
            -p 8000:8000 \
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
