import sys
import json
import pulumi
from pulumi import automation as auto
import pulumi_vsphere as vsphere


# Pulumi automation API test
# Inline Pulumi program
def pulumi_program():
    # Names of your resources in vSphere
    datastore_name = 'roels-bart'
    network_name = 'VM Network'
    resource_pool_name = 'Resources'
    datacenter_name = 'StudentDC'
    template_name = 'CleanUbuntu'

    # Vm settings
    vm_name = 'pulumi-vm'
    vm_memory = 1024
    vm_cpus = 1
    vm_disk_size = 20
    disk_scrub = False
    disk_thin = True
    diskl_label = 'disk0'
    
    # Vm customization
    vm_domain = 'test.local'
    vm_host_name = 'pulumi-vm'
    vm_ipv4_gateway = '192.168.50.1'
    vm_ipv4_netmask = 24
    vm_ipv4_address = '192.168.50.55'
    vm_dns_servers = ['172.20.4.140', '172.20.4.141']


    # Lookup the Datacenter by name
    datacenter = vsphere.get_datacenter(name=datacenter_name)

    # Lookup the Datastore by name
    datastore = vsphere.get_datastore(name=datastore_name, datacenter_id=datacenter.id)

    # Lookup network by name
    network = vsphere.get_network(name=network_name, datacenter_id=datacenter.id)

    # Default parent resource pool
    pool = vsphere.get_resource_pool(name=resource_pool_name, datacenter_id=datacenter.id)

    # Lookup template by name
    template = vsphere.get_virtual_machine(name=template_name, datacenter_id=datacenter.id)

    # Define customization specifications for the cloned VM
    customize_spec = vsphere.VirtualMachineCloneCustomizeArgs(
        # Other customization options can be added here
        dns_server_lists=vm_dns_servers,  # Set DNS servers
        ipv4_gateway=vm_ipv4_gateway, # Set the default gateway
        # Provide Linux-specific customization options
        linux_options=vsphere.VirtualMachineCloneCustomizeLinuxOptionsArgs(
            host_name=vm_host_name,  # Set the hostname for the Linux VM
            domain=vm_domain,  # Set the domain for the VM
            # Script to change password for user bart
        ),
        # Configure network interfaces on the VM.
        # You will need to create a `VirtualMachineCloneCustomizeNetworkInterfaceArgs`
        # for each network interface you want to customize.
        network_interfaces=[
            vsphere.VirtualMachineCloneCustomizeNetworkInterfaceArgs(
                ipv4_address=vm_ipv4_address,     # Set the static IPv4 address for the interface
                ipv4_netmask=vm_ipv4_netmask,                 # Set the netmask length
                dns_server_lists=vm_dns_servers  # Set DNS servers
            )
        ],
    )



    # Create a when this script is runned
    virtual_machine = vsphere.VirtualMachine("vm",
        name=vm_name,
        datastore_id=datastore.id,
        resource_pool_id=pool.id,
        num_cpus=vm_cpus,
        # Firmware EFI
        firmware='efi',
        memory=vm_memory,
        guest_id='ubuntu64Guest',
        scsi_type='pvscsi',
        network_interfaces=[{
            'network_id': network.id,
            'adapter_type': 'vmxnet3',
        }],
        clone={
            'template_uuid': template.id,
            'customize': customize_spec,
        },
        # Assing disk
        disks=[
            {
                'label': diskl_label,
                'size': vm_disk_size,
                'eagerly_scrub': disk_scrub,
                'thin_provisioned': disk_thin,
            },
        ],
    )



    # Export the virtual machine's properties
    pulumi.export('vm_name', virtual_machine.name)
    pulumi.export('vm_id', virtual_machine.id)
    pulumi.export('vm_ip_address', virtual_machine.guest_ip_addresses)
    pulumi.export('vm_default_ip', virtual_machine.default_ip_address)
    



#
# To destroy our program, we can run python main.py destroy
# 
destroy = False
args = sys.argv[1:]
if len(args) > 0:
    if args[0] == "destroy":
        destroy = True


#
# Associate with a stack
#
project_name = "inline_vsphere_project"
stack_name = "dev"
# create or select a stack matching the specified name and project.
# this will set up a workspace with everything necessary to run our inline program (pulumi_program)
stack = auto.create_or_select_stack(stack_name=stack_name,project_name=project_name,program=pulumi_program)
print("successfully initialized stack")

# Install stack plugins
print("installing plugins...")
stack.workspace.install_plugin("vsphere", "v4.9.1")
print("plugins installed")

# Set stack configuration specifying the vSphere endpoint and credentials
print("setting up config")
stack.set_config("vsphere:user", auto.ConfigValue(value="administrator@vsphere.local"))
stack.set_config("vsphere:password", auto.ConfigValue(value="P@ssw0rd", secret=True))
stack.set_config("vsphere:vsphereServer", auto.ConfigValue(value="192.168.50.10"))
stack.set_config("vsphere:allowUnverifiedSsl", auto.ConfigValue(value="true"))

# Refresh the stack
print("refreshing stack...")
stack.refresh(on_output=print)
print("refresh complete")

if destroy:
    print("destroying stack...")
    stack.destroy(on_output=print)
    print("stack destroy complete")
    sys.exit()


print("updating stack...")
up_res = stack.up(on_output=print)
print(f"update summary: \n{json.dumps(up_res.summary.resource_changes, indent=4)}")
