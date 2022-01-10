### Simple AWS cleaner

Finds VPC based upon wildcard term search and deletes it with all its
dependencies. 

There is a single non-native library - boto3 which you
may need to install. It's the AWS CLI python wrapper.

The -f argument provides a filter to search aws for your vpc by the
cluster name. Therefore it's recommended that your cluster name includes
an unambiguous substring such as your name.

Optional arguments are dry run, region setting and your AWS profile name
which you should be able to snag from ~/.aws/credentials in a default
config. Don't forget to renew this with MAWS if appropriate.
