import asyncio
import sys
import uuid
import subprocess
import os
import json
import yaml
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi import FastAPI, Request, Form, Depends, HTTPException, WebSocket, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from tinydb import TinyDB, Query
from urllib.parse import urlparse
import pulumi
from pulumi import automation as auto
import pulumi_vsphere as vsphere
import ansible_runner
from colorama import Fore, Style
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key='your_secret_key')

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# TinyDB and other global variables...
db = TinyDB('tinydb/deploy_vms.json')
vm_table = db.table('vms')

#
# TinyDB functions 
#
def save_vm_to_db(form_data):
    form_data['id'] = str(uuid.uuid4())  # Generate a unique ID for each VM
    vm_table.insert(form_data)
    print(f"{Fore.GREEN}Data saved to TinyDB{Style.RESET_ALL}")

def load_vm_from_db():
    return vm_table.all()

# 
# Socketio Section
#
active_sessions = {}
@app.websocket("/ws/logs/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_sessions[session_id] = websocket
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        del active_sessions[session_id]

#
# Routes
#

# Index page
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    print(f"{Fore.GREEN}Session Data: {request.session}{Style.RESET_ALL}")
    return templates.TemplateResponse("index.html", {"request": request})

# create vm page get
@app.get("/create_vm", response_class=HTMLResponse)
async def get_create_vm_page(request: Request):
    return templates.TemplateResponse("create_vm.html", {"request": request, "success": None, "message": None})

# create vm page post
@app.post("/create_vm", response_class=HTMLResponse)
async def post_create_vm(
    request: Request,
    vm_name: str = Form(...),
    vm_dns_servers: str = Form(...),
    vm_memory: int = Form(...),
    vm_cpus: int = Form(...),
    vm_disk_size: int = Form(...),
    datastore_name: str = Form(...),
    network_name: str = Form(...),
    resource_pool_name: str = Form(...),
    datacenter_name: str = Form(...),
    template_name: str = Form(...),
    disk_scrub: bool = Form(False),
    disk_thin: bool = Form(True),
    diskl_label: str = Form(...),
    vm_domain: str = Form(...),
    vm_host_name: str = Form(...),
    vm_ipv4_gateway: str = Form(...),
    vm_ipv4_netmask: int = Form(...),
    vm_ipv4_address: str = Form(...)
):
    form_data = {
        "vm_name": vm_name,
        "vm_dns_servers": vm_dns_servers.split(','),
        "vm_memory": vm_memory,
        "vm_cpus": vm_cpus,
        "vm_disk_size": vm_disk_size,
        "datastore_name": datastore_name,
        "network_name": network_name,
        "resource_pool_name": resource_pool_name,
        "datacenter_name": datacenter_name,
        "template_name": template_name,
        "disk_scrub": disk_scrub,
        "disk_thin": disk_thin,
        "diskl_label": diskl_label,
        "vm_domain": vm_domain,
        "vm_host_name": vm_host_name,
        "vm_ipv4_gateway": vm_ipv4_gateway,
        "vm_ipv4_netmask": vm_ipv4_netmask,
        "vm_ipv4_address": vm_ipv4_address
    }

    success = None
    message = None

    print(f"{Fore.GREEN}Form Data: {form_data}{Style.RESET_ALL}")

    if len(vm_table) == 0:
        form_data['id'] = '1'
        message = 'VM created'
        success = True
        save_vm_to_db(form_data)
    else:
        message = 'There is already one VM in the database. Delete your VM first before creating a new one.'
        success = False

    return templates.TemplateResponse("create_vm.html", {"request": request, "success": success, "message": message})

# delete vm page post
@app.post("/delete_vm", response_class=HTMLResponse)
async def post_delete_vm(request: Request, vm_id: str = Form(...)):
    vm_data = vm_table.search(Query().id == vm_id)
    if vm_data:
        vm_table.remove(Query().id == vm_id)
        return templates.TemplateResponse("create_vm.html", {"request": request, "success": True, "message": "VM deleted"})
    else:
        return templates.TemplateResponse("create_vm.html", {"request": request, "success": False, "message": "VM not found"})


#
# Deploy VMs page Section
#

# global variable
par_datastore_name = 'roels-bart'
par_network_name = 'VM Network'
par_resource_pool_name = 'Resources'
par_datacenter_name = 'StudentDC'
par_template_name = 'CleanUbuntu'
par_vm_name = 'pulumi-vm'
par_vm_memory = 1024
par_vm_cpus = 1
par_vm_disk_size = 20
par_disk_scrub = False
par_disk_thin = True
par_diskl_label = 'disk0'
par_vm_domain = 'test.local'
par_vm_host_name = 'pulumi-vm'
par_vm_ipv4_gateway = ''
par_vm_ipv4_netmask = 24
par_vm_ipv4_address = ''
par_vm_dns_servers = ['']

par_vsphere_user = ''
par_vsphere_password = ''
par_vsphere_server = ''
par_vsphere_allow_unverified_ssl = True 

# Pulumi Program
def pulumi_program():
    # Access global variables
    global par_datastore_name
    global par_network_name
    global par_resource_pool_name
    global par_datacenter_name
    global par_template_name
    global par_vm_name
    global par_vm_memory
    global par_vm_cpus
    global par_vm_disk_size
    global par_disk_scrub
    global par_disk_thin
    global par_diskl_label
    global par_vm_domain
    global par_vm_host_name
    global par_vm_ipv4_gateway
    global par_vm_ipv4_netmask
    global par_vm_ipv4_address
    global par_vm_dns_servers



    # Names of your resources in vSphere
    datastore_name = par_datastore_name
    network_name = par_network_name
    resource_pool_name = par_resource_pool_name
    datacenter_name = par_datacenter_name
    template_name = par_template_name

    # Vm settings
    vm_name = par_vm_name
    vm_memory = par_vm_memory
    vm_cpus = par_vm_cpus
    vm_disk_size = par_vm_disk_size
    disk_scrub = par_disk_scrub
    disk_thin = par_disk_thin
    diskl_label = par_diskl_label
    
    # Vm customization
    vm_domain = par_vm_domain
    vm_host_name = par_vm_host_name
    vm_ipv4_gateway = par_vm_ipv4_gateway
    vm_ipv4_netmask = par_vm_ipv4_netmask
    vm_ipv4_address = par_vm_ipv4_address
    vm_dns_servers = par_vm_dns_servers

    print(f"{Fore.GREEN}VM Data: {par_vm_dns_servers}{Style.RESET_ALL}")


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
        # Adding disk
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



    # Async function to deploy VM with Pulumi

# Async function to deploy VM with Pulumi
def deploy_vm_with_pulumi_flfl(vm_id, vsphere_user, vsphere_password, vsphere_server, vsphere_allow_unverified_ssl, session_id):
    # Retrieve specific VM data based on the ID
    vm_data = vm_table.search(Query().id == vm_id)
    
    if vm_data:
        print(f"{Fore.GREEN}Deploying VM: {vm_id}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}VM Data: {vm_data}{Style.RESET_ALL}")

        # Set global variables
        global par_datastore_name, par_network_name,par_resource_pool_name, par_datacenter_name, par_template_name, par_vm_name, par_vm_memory, par_vm_cpus, par_vm_disk_size, par_disk_scrub, par_disk_thin, par_diskl_label, par_vm_domain, par_vm_host_name, par_vm_ipv4_gateway, par_vm_ipv4_netmask, par_vm_ipv4_address, par_vm_dns_servers

        # Set global variables
        par_datastore_name = vm_data[0]['datastore_name']
        par_network_name = vm_data[0]['network_name']
        par_resource_pool_name = vm_data[0]['resource_pool_name']
        par_datacenter_name = vm_data[0]['datacenter_name']
        par_template_name = vm_data[0]['template_name']
        par_vm_name = vm_data[0]['vm_name']
        par_vm_memory = vm_data[0]['vm_memory']
        par_vm_cpus = vm_data[0]['vm_cpus']
        par_vm_disk_size = vm_data[0]['vm_disk_size']
        par_disk_scrub = vm_data[0]['disk_scrub']
        par_disk_thin = vm_data[0]['disk_thin']
        par_diskl_label = vm_data[0]['diskl_label']
        par_vm_domain = vm_data[0]['vm_domain']
        par_vm_host_name = vm_data[0]['vm_host_name']
        par_vm_ipv4_gateway = vm_data[0]['vm_ipv4_gateway']
        par_vm_ipv4_netmask = vm_data[0]['vm_ipv4_netmask']
        par_vm_ipv4_address = vm_data[0]['vm_ipv4_address']
        par_vm_dns_servers = vm_data[0]['vm_dns_servers']

        # Log system 
        async def on_output(log_message: str):
            if session_id in active_sessions:
                websocket = active_sessions[session_id]
                await websocket.send_text(log_message)


        # Create or select a Pulumi stack
        project_name = "inline_vsphere_project"
        stack_name = "testing"

        # Stack configuration
        stack = auto.create_or_select_stack(stack_name=stack_name, project_name=project_name, program=pulumi_program)

        # Pulumi refresh to get the current state
        print("refreshing stack to get state...")
        stack.refresh(on_output=lambda message: asyncio.run(on_output(message)))
        print("refresh complete")

        # for inline programs, we must manage plugins ourselves
        print("installing plugins...")
        # Install stack plugins
        stack.workspace.install_plugin("vsphere", "v4.9.1")
        print("plugins installed")

        # Set stack configuration
        print("setting up config")
        stack.set_config("vsphere:user", auto.ConfigValue(value=vsphere_user))
        stack.set_config("vsphere:password", auto.ConfigValue(value=vsphere_password, secret=True))
        stack.set_config("vsphere:vsphereServer", auto.ConfigValue(value=vsphere_server))
        stack.set_config("vsphere:allowUnverifiedSsl", auto.ConfigValue(value=str(vsphere_allow_unverified_ssl).lower()))
        print("config set")


        # In your deploy_vm_with_pulumi_async function
        up_res = stack.up(on_output=lambda message: asyncio.run(on_output(message)))
        print("updating stack...")
        print(f"update summary: \n{json.dumps(up_res.summary.resource_changes, indent=4)}")
    else:
        print(f"{Fore.RED}VM with ID {vm_id} not found{Style.RESET_ALL}")

# FastAPI route for deploying VMs with Pulumi
@app.post("/deploy_vms_with_pulumi")
async def deploy_vm_with_pulumi(request: Request, background_tasks: BackgroundTasks, vm_id: str = Form(...)):

    # Extract session variables
    vsphere_user = request.session.get('vsphere_user')
    vsphere_password = request.session.get('vsphere_password')
    vsphere_server = request.session.get('vsphere_server')
    vsphere_allow_unverified_ssl = request.session.get('vsphere_allow_unverified_ssl', 'true')
    session_id = str(uuid.uuid4())  # Generate a unique session ID

    print(f"Sesssion ID: {session_id}")

    # Start the Pulumi deployment in the background
    # Add the Pulumi deployment task to run in the background
    background_tasks.add_task(deploy_vm_with_pulumi_flfl, vm_id, vsphere_user, vsphere_password, vsphere_server, vsphere_allow_unverified_ssl, session_id)

    # Pass the session ID to the template and return immediately
    return templates.TemplateResponse("pulumi_logs.html", {"request": request, "session_id": session_id})

# FastAPI route for displaying VMs
@app.get('/deploy_vms', response_class=HTMLResponse)
async def deploy_vm(request: Request):
    vm_data = load_vm_from_db()
    session = request.session  # Access session data
    return templates.TemplateResponse('start_vm.html', {'request': request, 'vm_data': vm_data, 'session': session})

# FastAPI route for logs
@app.get('/pulumi_logs', response_class=HTMLResponse)
async def get_pulumi_logs(request: Request):
    return templates.TemplateResponse('pulumi_logs.html', {"request": request})

#
# Vsphere settings page
#
@app.get('/vsphere_setting', response_class=HTMLResponse)
async def get_vsphere_setting(request: Request):
    display_data = {
        'vsphere_user': request.session.get('vsphere_user'),
        'vsphere_password': '********' if request.session.get('vsphere_password') else None,
        'vsphere_server': request.session.get('vsphere_server'),
        'vsphere_allow_unverified_ssl': request.session.get('vsphere_allow_unverified_ssl', 'true')
    }
    return templates.TemplateResponse('vsphere_setting_config.html', {'request': request, 'display_data': display_data})

@app.post('/vsphere_setting')
async def post_vsphere_setting(request: Request, 
                               vcenter_username: str = Form(...), 
                               vcenter_password: str = Form(...), 
                               vcenter_host: str = Form(...), 
                               vsphere_allow_unverified_ssl: str = Form(...)):
    request.session['vsphere_user'] = vcenter_username
    request.session['vsphere_password'] = vcenter_password
    request.session['vsphere_server'] = vcenter_host
    # if checkbox is checked, the value is 'true', otherwise it's 'false'
    if(vsphere_allow_unverified_ssl == 'on'):
        request.session['vsphere_allow_unverified_ssl'] = 'true'
    else:
        request.session['vsphere_allow_unverified_ssl'] = 'false'

    return RedirectResponse(url='/vsphere_setting', status_code=303)

@app.post('/vsphere_setting_edit')
async def vsphere_setting_edit(request: Request):
    request.session.clear()
    return RedirectResponse(url='/vsphere_setting', status_code=303)


#
# Ansible Section
#

def run_ansible_playbook(playbook_path, inventory_path, extra_vars, session_id):
    def event_handler(event):
        # Process events from Ansible Runner
        # Modify this logic as per your requirements
        if 'event_data' in event:
            event_data = event['event_data']
            if 'task' in event_data and 'res' in event_data:
                task_info = {
                    "task": event_data['task'],
                    "status": event_data['res'].get('changed', False),
                    "details": event_data['res'].get('msg', ''),
                    "timestamp": event_data.get('created', '')
                }
                # Emit task info to WebSocket
                if session_id in active_sessions:
                    active_sessions[session_id].send_text(f"Task Update: {task_info}")
            elif 'stdout' in event_data:
                if session_id in active_sessions:
                    active_sessions[session_id].send_text(f"STDOUT: {event_data['stdout']}")

        if event['event'] == 'playbook_on_stats':
            recap = event.get('event_data', {}).get('playbook_stats', {})
            if session_id in active_sessions:
                active_sessions[session_id].send_text(f"Playbook Recap: {recap}")

    try:
        runner = ansible_runner.run(
            playbook=playbook_path,
            inventory=inventory_path,
            extravars=extra_vars,
            event_handler=event_handler
        )
        print("Playbook run status:", runner.status)
        print("Playbook run stats:", runner.stats)

        # Notify completion
        if session_id in active_sessions:
            active_sessions[session_id].send_text("Playbook execution completed")
    except Exception as e:
        print("Error running the Ansible playbook:", e)
        # Notify error
        if session_id in active_sessions:
            active_sessions[session_id].send_text(f"Error: {e}")


# Route to run Ansible playbook
@app.post("/run_ansible_playbook")
async def run_ansible_playbook_route(background_tasks: BackgroundTasks):
    playbook_path = os.path.join(os.getcwd(), 'ansible', 'playbook.yml')
    inventory_path = os.path.join(os.getcwd(), 'ansible', 'inventory.json')
    extra_vars = {}  # or any extra vars you need to pass

    session_id = str(uuid.uuid4())  # Unique session ID for WebSocket communication

    # Add the Ansible playbook execution as a background task
    background_tasks.add_task(run_ansible_playbook, playbook_path, inventory_path, extra_vars, session_id)

    # Redirect to the Ansible log page transfer session ID but not in the URL
    return RedirectResponse(url=f'/ansible_logs?session_id={session_id}', status_code=303)


# Route to run ansible lgos 
@app.get("/ansible_logs")
async def ansible_logs(request: Request):
    return templates.TemplateResponse("ansible_logs.html", {"request": request})

# Asnible code to deploy app
@app.post("/deploy_app", response_class=HTMLResponse)
async def deploy_app(background_tasks: BackgroundTasks,repo_url: str = Form(...),docker_compose_project_src: str = Form(...),docker_file: str = Form(None)):
    repo_type = 'private' if repo_url.startswith('git@github.com:') else 'public'
    project_src = f'/home/{{{{ ansible_user }}}}/app/{docker_compose_project_src}' if docker_compose_project_src else '/home/{{{{ ansible_user }}}}/app'
    
    generate_ansible_inventory()

    playbook_path = os.path.join(os.getcwd(), 'ansible', 'playbook_deploy_app.yaml')
    inventory_path = os.path.join(os.getcwd(), 'ansible', 'inventory.json')
    extra_vars = {
        'repo_url': repo_url,
        'project_src': project_src,
        'docker_file': docker_file,
        'repo_type': repo_type
    }

    # Create unique session ID for WebSocket
    session_id = str(uuid.uuid4())

    # Run playbook as background task
    background_tasks.add_task(
        run_ansible_playbook_async,
        playbook_path,
        inventory_path,
        extra_vars,
        session_id
    )

    # Render template or redirect
    return templates.TemplateResponse("ansible_logs.html", {"request": request, "session_id": session_id})

# Ansible code to get ssh key
@app.post("/generate_ssh_keys", response_class=JSONResponse)
async def generate_ssh_keys(vm_id: str = Form(...)):
    generate_ansible_inventory()
    playbook_path = os.path.join(os.getcwd(), 'ansible', 'generate_keys.yaml')
    inventory_path = os.path.join(os.getcwd(), 'ansible', 'inventory.json')

    status = run_ssh_key_generation_playbook(playbook_path, inventory_path)

    hostname = None
    vm_data = vm_table.search(Query().id == vm_id)
    if vm_data:
        hostname = vm_data[0]['vm_name']

    if hostname:
        try:
            with open(f'/tmp/ssh_key_rsa_{hostname}.pub', 'r') as file:
                ssh_key = file.read()
            return {"status": "successful", "ssh_key": ssh_key}
        except IOError:
            raise HTTPException(status_code=500, detail="Unable to read SSH key file")
    else:
        raise HTTPException(status_code=404, detail="VM data not found or is empty")

# Ansible code to run ssh key generation playbook
def run_ssh_key_generation_playbook(playbook_path, inventory_path):
    r = ansible_runner.run(private_data_dir='/path/to/ansible/playbook/directory', playbook='ssh_key_gen.yml')
    return r.status

#
# Run
# 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)