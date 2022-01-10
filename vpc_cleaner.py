#! /usr/bin/python3
# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Author: Dave Whitehouse
# Created: Date: 5 Jan 22
# Contact: @David Whitehouse
# ---------------------------------------------------------------------------
""" Finds VPC based upon wildcard term search and deletes it with all its
    dependencies. There is a single non-native library - boto3 which you
    may need to install. It's the AWS CLI python wrapper.

    The -f argument provides a filter to search aws for your vpc by the
    cluster name. Therefore it's recommended that your cluster name includes
    an unambiguous substring such as your name.

    Optional arguments are dry run, region setting and your AWS profile name
    which you should be able to snag from ~/.aws/credentials in a default
    config. Don't forget to renew this with MAWS if appropriate.
"""
# ---------------------------------------------------------------------------

import sys
import boto3
import argparse
from botocore.exceptions import ClientError
from colorama import Fore


# Parse user arguments and assign to vars

parser = argparse.ArgumentParser(description='Finds an AWS VPC based upon wildcard term search and deletes it with '
                                             'all its dependencies')
parser.add_argument('-f', '--filter-term', help='Provide a search term for object names, ie whitehouse. Do not use '
                                                'regex or add wildcard characters', required=True)
parser.add_argument('-r', '--aws-region', help='Define AWS region, ie us-west-2', default='us-west-2')
parser.add_argument('-d', '--dry-run', help='Dry run only', default=False, action='store_true')
parser.add_argument('-p', '--profile-name', help='AWS Profile name, ie 222638339470_Mesosphere-PowerUser',
                    default='222638339470_Mesosphere-PowerUser')
args = parser.parse_args()
dry_run = args.dry_run
aws_region = args.aws_region
filter_term = args.filter_term
profile_name = args.profile_name

# Instantiate an AWS client
boto3.setup_default_session(profile_name='222638339470_Mesosphere-PowerUser')
ec2 = boto3.resource('ec2', region_name=aws_region)
client = boto3.client("ec2", region_name=aws_region)
ec2client = ec2.meta.client

# Search by filter for the cluster name and add the vpc Ids to an array
try:
    filt = [{'Name': 'tag:Name', 'Values': [f"*{filter_term}*"]}]
    vpcs = list(ec2.vpcs.filter(Filters=filt))
except ClientError as e:
    print(Fore.RED + "Unable to connect to AWS - check that you have valid creds. Refresh if necessary." + Fore.RESET)
    sys.exit()


def vpc_cleanup(vpcid):
    """
    Clear the cruft from a VPC
    """
    if not vpcid:
        print('VPC id was not provided. Exiting')
        return
    print(f'Starting to Removing VPC artefacts: {vpcid}')
    vpc = ec2.Vpc(vpcid)

    # START NUKING STUFF

    # bin instances
    for subnet in vpc.subnets.all():
        for instance in subnet.instances.all():
            print(f"Deleting the following Instance: {instance}")
            if not dry_run:
                instance.terminate()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)

    # bin routing tables
    for rt in vpc.route_tables.all():
        for rta in rt.associations:
            print(f"Deleting the following routing table associations: {rta}", end='.....')
            if not rta.main and not dry_run:
                try:
                    rta.delete()
                    print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
                except ClientError as e:
                    print(Fore.RED + f"Failed to delete route table associations: {rta} - {e}" + Fore.RESET)
                    pass
        for r in rt.routes:
            print(f"Deleting the following routing table routes: {r}")
            if not dry_run:
                try:
                    r.delete()
                    print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
                except ClientError as e:
                    print(Fore.RED + f"Failed to delete route: {r} - {e}" + Fore.RESET)
                    pass
        print(f"Deleting the routing table: {rt}")
        if not dry_run:
            try:
                rt.delete()
                print(Fore.GREEN + f"Successfully Completed" + Fore.RESET)
            except ClientError as e:
                print(Fore.RED + f"Failed to delete routing table: {rt} - {e}" + Fore.RESET)
                pass

    # bin internet gateways
    i_gateways = client.describe_internet_gateways(Filters=filt).get("InternetGateways")
    for i_gateway in i_gateways:
        i_gateway = i_gateway['InternetGatewayId']
        print(f"Deleting internet gateway - {i_gateway}")
        if not dry_run:
            try:
                vpc.detach_internet_gateway(InternetGatewayId=i_gateway)
                ec2.InternetGateway(i_gateway).delete()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError as e:
                print(Fore.RED + f'Dependency error with internet gateway: {i_gateway} - {e}' + Fore.RESET)

    # bin nat gateways
    gw_filter = [{'Name': 'vpc-id', 'Values': [vpcid]}]
    gateways = client.describe_nat_gateways(Filters=gw_filter).get("NatGateways")
    for gateway in gateways:
        gateway = str(gateway['NatGatewayId'])
        print(f"Deleting NAT gateway - {gateway}")
        if not dry_run:
            try:
                client.delete_nat_gateway(NatGatewayId=gateway)
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError as e:
                print(Fore.RED + f'Dependency error with nat gateway: {gateway} - {e}' + Fore.RESET)

    # release elastic ips
    for eip_list in client.describe_addresses(Filters=filt)['Addresses']:
        eip = eip_list['AllocationId']
        print(f"Releasing Elastic IP: {eip}")
        if not dry_run:
            try:
                client.release_address(AllocationId=eip)
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError:
                print(Fore.RED + f'Dependency error with elastic ip: {eip}' + Fore.RESET)

    # bin subnets
    for subnet in vpc.subnets.all():
        print(f"Deleting subnet: {subnet}")
        if not dry_run:
            try:
                subnet.delete()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError:
                print(Fore.RED + f'Dependency error with {subnet}' + Fore.RESET)

    # bin endpoints
    for ep in ec2client.describe_vpc_endpoints(
            Filters=[{
                'Name': 'vpc-id',
                'Values': [vpcid]
            }])['VpcEndpoints']:
        print(f"Deleting endpoint: {ep}")
        if not dry_run:
            ec2client.delete_vpc_endpoints(VpcEndpointIds=[ep['VpcEndpointId']])

    # bin security groups
    sg_failures = []
    for sg in vpc.security_groups.all():
        if sg.group_name != 'default':
            print(f"Deleting Security Group Rules: {sg}")
            if not dry_run:
                try:
                    if sg.ip_permissions:
                        sg.revoke_ingress(IpPermissions=sg.ip_permissions)
                        sg.revoke_egress(IpPermissions=sg.ip_permissions)
                    sg.delete()
                    print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
                except ClientError as f:
                    print(Fore.RED + f'Dependency error with {sg} - will have another go' + Fore.RESET)
                    sg_failures.append(sg)

    # We sometimes get interdependency issues. Have another go with the array reversed
    if len(sg_failures) > 0:
        sg_failures.reverse()
        for failure in sg_failures:
            try:
                if failure.ip_permissions:
                    failure.revoke_ingress(IpPermissions=failure.ip_permissions)
                    failure.revoke_egress(IpPermissions=failure.ip_permissions)
                failure.delete()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError as f:
                print(Fore.RED + f'Could not rectify the dependency error with {failure}. Rectify manually then retry'
                      + Fore.RESET)
                # sys.exit()

    # bin network interfaces
    for subnet in vpc.subnets.all():
        for interface in subnet.network_interfaces.all():
            print(f"Deleting interface: {interface}")
            if not dry_run:
                try:
                    interface.delete()
                    print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
                except ClientError:
                    print(Fore.RED + f'Dependency error with network interface: {interface}' + Fore.RESET)

    # bin any vpc peering connections
    vpc_failures = []
    for vpcpeer in ec2client.describe_vpc_peering_connections(
            Filters=[{
                'Name': 'requester-vpc-info.vpc-id',
                'Values': [vpcid]
            }])['VpcPeeringConnections']:
        print(f"Deleting peer connection: {vpcpeer}")
        if not dry_run:
            try:
                ec2.VpcPeeringConnection(vpcpeer['VpcPeeringConnectionId']).delete()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
            except ClientError as e:
                print(Fore.RED + f'Dependency error with {vpcpeer}' + Fore.RESET)
                vpc_failures.append(vpcpeer)

    # bin non-default network acls
    for netacl in vpc.network_acls.all():
        if not netacl.is_default:
            print(f"Deleting ACL: {netacl}")
            if not dry_run:
                netacl.delete()
                print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)

    # finally, bin the vpc
    print(f"Deleting the VPC: {vpcid}")
    if not dry_run:
        try:
            ec2client.delete_vpc(VpcId=vpcid)
            print(Fore.GREEN + f"Succesfully Completed" + Fore.RESET)
        except ClientError as e:
            print(Fore.RED + f"Could not delete the VPC: {vpcid}" + Fore.RESET)


if __name__ == '__main__':
    # Iterate through our matching vpcs through the cleanup function
    for my_vpc in vpcs:
        target = str(my_vpc).split("'")[1]
        vpc_cleanup(target)
        print(f'\n\nVPC {target} Complete\n\n')
