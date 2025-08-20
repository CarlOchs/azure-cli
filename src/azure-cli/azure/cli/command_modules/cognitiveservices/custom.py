# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from typing import IO, Any, AnyStr, Dict, List, Optional, Union

from knack.util import CLIError
from knack.log import get_logger

from os import PathLike

from azure.cli.core.azclierror import FileOperationError, InvalidArgumentValueError
from azure.mgmt.cognitiveservices.models import Account as CognitiveServicesAccount, Sku, \
    VirtualNetworkRule, IpRule, NetworkRuleSet, NetworkRuleAction, \
    AccountProperties as CognitiveServicesAccountProperties, ApiProperties as CognitiveServicesAccountApiProperties, \
    Identity, ResourceIdentityType as IdentityType, \
    Deployment, DeploymentModel, DeploymentScaleSettings, DeploymentProperties, \
    CommitmentPlan, CommitmentPlanProperties, CommitmentPeriod, CapabilityHost, CapabilityHostProperties,\
    Project, ProjectProperties, ConnectionUpdateContent, ConnectionPropertiesV2BasicResource
    
from azure.cli.command_modules.cognitiveservices._client_factory import cf_accounts, cf_resource_skus
from azure.cli.command_modules.cognitiveservices._utils import get_mapped_mlconn_type, get_valid_mlconn_types

logger = get_logger(__name__)


def list_resources(client, resource_group_name=None):
    """
    List all Azure Cognitive Services accounts.
    """
    if resource_group_name:
        return client.list_by_resource_group(resource_group_name)
    return client.list()


def recover(client, location, resource_group_name, account_name):
    """
    Recover a deleted Azure Cognitive Services account.
    """
    properties = CognitiveServicesAccountProperties()
    properties.restore = True
    params = CognitiveServicesAccount(properties=properties)
    params.location = location

    return client.begin_create(resource_group_name, account_name, params)


def list_usages(client, resource_group_name, account_name):
    """
    List usages for Azure Cognitive Services account.
    """
    return client.list_usages(resource_group_name, account_name).value


def list_kinds(client):
    """
    List all valid kinds for Azure Cognitive Services account.

    :param client: the ResourceSkusOperations
    :return: a list
    """
    # The client should be ResourceSkusOperations, and list() should return a list of SKUs for all regions.
    # The sku will have "kind" and we use that to extract full list of kinds.
    kinds = {x.kind for x in client.list()}
    return sorted(list(kinds))


def list_skus(cmd, kind=None, location=None, resource_group_name=None, account_name=None):
    """
    List skus for Azure Cognitive Services account.
    """
    if resource_group_name is not None or account_name is not None:
        logger.warning(
            'list-skus with an existing account has been deprecated and will be removed in a future release.')
        if resource_group_name is None:
            # account_name must not be None
            raise CLIError('--resource-group is required when --name is specified.')
        # keep the original behavior to avoid breaking changes
        return cf_accounts(cmd.cli_ctx).list_skus(resource_group_name, account_name)

    # in other cases, use kind and location to filter SKUs
    def _filter_sku(_sku):
        if kind is not None:
            if _sku.kind != kind:
                return False
        if location is not None:
            if location.lower() not in [x.lower() for x in _sku.locations]:
                return False
        return True

    return [x for x in cf_resource_skus(cmd.cli_ctx).list() if _filter_sku(x)]


def create(
        client, resource_group_name, account_name, sku_name, kind, location, custom_domain=None,
        tags=None, api_properties=None, assign_identity=False, storage=None, encryption=None,
        allow_project_management=True,
        yes=None):  # pylint: disable=unused-argument
    """
    Create an Azure Cognitive Services account.
    """

    sku = Sku(name=sku_name)

    properties = CognitiveServicesAccountProperties()
    if api_properties is not None:
        api_properties = CognitiveServicesAccountApiProperties.deserialize(api_properties)
        properties.api_properties = api_properties
    if custom_domain:
        properties.custom_sub_domain_name = custom_domain
    properties.allow_project_management = allow_project_management
    params = CognitiveServicesAccount(sku=sku, kind=kind, location=location,
                                      properties=properties, tags=tags)
    if assign_identity:
        params.identity = Identity(type=IdentityType.system_assigned)

    if storage is not None:
        params.properties.user_owned_storage = json.loads(storage)

    if encryption is not None:
        params.properties.encryption = json.loads(encryption)

    return client.begin_create(resource_group_name, account_name, params)


def update(client, resource_group_name, account_name, sku_name=None, custom_domain=None,
           tags=None, api_properties=None, storage=None, encryption=None):
    """
    Update an Azure Cognitive Services account.
    """
    if sku_name is None:
        sa = client.get(resource_group_name, account_name)
        sku_name = sa.sku.name

    sku = Sku(name=sku_name)

    properties = CognitiveServicesAccountProperties()
    if api_properties is not None:
        api_properties = CognitiveServicesAccountApiProperties.deserialize(api_properties)
        properties.api_properties = api_properties
    if custom_domain:
        properties.custom_sub_domain_name = custom_domain
    params = CognitiveServicesAccount(sku=sku, properties=properties, tags=tags)

    if storage is not None:
        params.properties.user_owned_storage = json.loads(storage)

    if encryption is not None:
        params.properties.encryption = json.loads(encryption)

    return client.begin_update(resource_group_name, account_name, params)


def default_network_acls():
    rules = NetworkRuleSet()
    rules.default_action = NetworkRuleAction.deny
    rules.ip_rules = []
    rules.virtual_network_rules = []
    return rules


def list_network_rules(client, resource_group_name, account_name):
    """
    List network rules for Azure Cognitive Services account.
    """
    sa = client.get(resource_group_name, account_name)
    rules = sa.properties.network_acls
    if rules is None:
        rules = default_network_acls()
    return rules


def add_network_rule(client, resource_group_name, account_name, subnet=None,
                     vnet_name=None, ip_address=None):  # pylint: disable=unused-argument
    """
    Add a network rule for Azure Cognitive Services account.
    """
    sa = client.get(resource_group_name, account_name)
    rules = sa.properties.network_acls
    if rules is None:
        rules = default_network_acls()

    if subnet:
        from azure.mgmt.core.tools import is_valid_resource_id
        if not is_valid_resource_id(subnet):
            raise CLIError("Expected fully qualified resource ID: got '{}'".format(subnet))

        if not rules.virtual_network_rules:
            rules.virtual_network_rules = []
        rules.virtual_network_rules.append(VirtualNetworkRule(id=subnet, ignore_missing_vnet_service_endpoint=True))
    if ip_address:
        if not rules.ip_rules:
            rules.ip_rules = []
        rules.ip_rules.append(IpRule(value=ip_address))

    properties = CognitiveServicesAccountProperties()
    properties.network_acls = rules
    params = CognitiveServicesAccount(properties=properties)

    return client.begin_update(resource_group_name, account_name, params)


def remove_network_rule(client, resource_group_name, account_name, ip_address=None, subnet=None,
                        vnet_name=None):  # pylint: disable=unused-argument
    """
    Remove a network rule for Azure Cognitive Services account.
    """
    sa = client.get(resource_group_name, account_name)
    rules = sa.properties.network_acls
    if rules is None:
        # nothing to update, but return the object
        return client.update(resource_group_name, account_name)

    if subnet:
        rules.virtual_network_rules = [x for x in rules.virtual_network_rules
                                       if not x.id.endswith(subnet)]
    if ip_address:
        rules.ip_rules = [x for x in rules.ip_rules if x.value != ip_address]

    properties = CognitiveServicesAccountProperties()
    properties.network_acls = rules
    params = CognitiveServicesAccount(properties=properties)

    return client.begin_update(resource_group_name, account_name, params)


def identity_assign(client, resource_group_name, account_name):
    """
    Assign the identity for Azure Cognitive Services account.
    """
    params = CognitiveServicesAccount()
    params.identity = Identity(type=IdentityType.system_assigned)
    sa = client.begin_update(resource_group_name, account_name, params).result()
    return sa.identity if sa.identity else {}


def identity_remove(client, resource_group_name, account_name):
    """
    Remove the identity for Azure Cognitive Services account.
    """
    params = CognitiveServicesAccount()
    params.identity = Identity(type=IdentityType.none)
    return client.begin_update(resource_group_name, account_name, params)


def identity_show(client, resource_group_name, account_name):
    """
    Show the identity for Azure Cognitive Services account.
    """
    sa = client.get(resource_group_name, account_name)
    return sa.identity if sa.identity else {}


def deployment_begin_create_or_update(
        client, resource_group_name, account_name, deployment_name,
        model_format, model_name, model_version, model_source=None,
        sku_name=None, sku_capacity=None,
        scale_settings_scale_type=None, scale_settings_capacity=None):
    """
    Create a deployment for Azure Cognitive Services account.
    """
    dpy = Deployment()
    dpy.properties = DeploymentProperties()
    dpy.properties.model = DeploymentModel()
    dpy.properties.model.format = model_format
    dpy.properties.model.name = model_name
    dpy.properties.model.version = model_version
    if model_source is not None:
        dpy.properties.model.source = model_source
    if sku_name is not None:
        dpy.sku = Sku(name=sku_name)
        dpy.sku.capacity = sku_capacity
    if scale_settings_scale_type is not None:
        dpy.properties.scale_settings = DeploymentScaleSettings()
        dpy.properties.scale_settings.scale_type = scale_settings_scale_type
        dpy.properties.scale_settings.capacity = scale_settings_capacity

    return client.begin_create_or_update(resource_group_name, account_name, deployment_name, dpy, polling=False)


def commitment_plan_create_or_update(
        client, resource_group_name, account_name, commitment_plan_name,
        hosting_model, plan_type, auto_renew,
        current_tier=None, current_count=None,
        next_tier=None, next_count=None):
    """
    Create a commitment plan for Azure Cognitive Services account.
    """
    plan = CommitmentPlan()
    plan.properties = CommitmentPlanProperties()
    plan.properties.hosting_model = hosting_model
    plan.properties.plan_type = plan_type
    if (current_tier is not None or current_count is not None):
        plan.properties.current = CommitmentPeriod()
        plan.properties.current.tier = current_tier
        plan.properties.current.count = current_count
    if (next_tier is not None or next_count is not None):
        plan.properties.next = CommitmentPeriod()
        plan.properties.next.tier = next_tier
        plan.properties.next.count = next_count
    plan.properties.auto_renew = auto_renew
    return client.create_or_update(resource_group_name, account_name, commitment_plan_name, plan)

def _from_ml_connection(mlconn):
    import azure.mgmt.cognitiveservices.models as models
    import azure.ai.ml.entities as ml_entities
    conn = None
    connection_category = get_mapped_mlconn_type(mlconn.type)
    if connection_category is None:
        raise InvalidArgumentValueError(
            f"Invalid connection type '{mlconn.type}'. ",
            recommendation=[
                "Verify that the connection type property is set to one of the following values:",
                ', '.join(get_valid_mlconn_types())
                ]
        )
    match type(mlconn.credentials):
        case ml_entities.PatTokenConfiguration:
            conn = models.PATAuthTypeConnectionProperties(
                credentials=models.ConnectionPersonalAccessToken(pat=mlconn.credentials.pat))
        case ml_entities.SasTokenConfiguration:
            conn = models.SASAuthTypeConnectionProperties(
                credentials=models.ConnectionSharedAccessSignature(sas=mlconn.credentials.sas_token))
        case ml_entities.UsernamePasswordConfiguration:
            conn = models.UsernamePasswordAuthTypeConnectionProperties(
                credentials=models.ConnectionUsernamePassword(
                    username=mlconn.credentials.username,
                    password=mlconn.credentials.password))
        case ml_entities.ManagedIdentityConfiguration:
            conn = models.ManagedIdentityAuthTypeConnectionProperties(
                credentials=models.ConnectionManagedIdentity(
                    client_id=mlconn.credentials.client_id,
                    resource_id=mlconn.credentials.resource_id,
                ))
        case ml_entities.ServicePrincipalConfiguration:
            conn = models.ServicePrincipalAuthTypeConnectionProperties(
                credentials=models.ConnectionServicePrincipal(
                    client_id=mlconn.credentials.client_id,
                    client_secret=mlconn.credentials.client_secret,
                    tenant_id=mlconn.credentials.tenant_id
                ))
        case ml_entities.AccessKeyConfiguration:
            conn = models.AccessKeyAuthTypeConnectionProperties(
                credentials=models.ConnectionAccessKey(
                    access_key_id=mlconn.credentials.access_key_id,
                    secret_access_key=mlconn.credentials.secret_access_key
                )
            )
        case ml_entities.ApiKeyConfiguration:
            conn = models.ApiKeyAuthConnectionProperties(
                credentials=models.ConnectionApiKey(key=mlconn.credentials.key)
            )
        case ml_entities.NoneCredentialConfiguration:
            conn = models.NoneAuthTypeConnectionProperties()
        case ml_entities.AccountKeyConfiguration:
            conn = models.AccountKeyAuthTypeConnectionProperties(
                credentials=models.ConnectionAccountKey(
                    key=mlconn.credentials.account_key
                )
            )
        case ml_entities.AadCredentialConfiguration:
            conn = models.AADAuthTypeConnectionProperties()
        case _:
            conn = models.AADAuthTypeConnectionProperties()
    conn.category = connection_category
    conn.target = mlconn.target
    conn.description = mlconn.description
    conn.metadata = mlconn.metadata
    return conn

def _load_connection_from_file(
    source: Union[str, PathLike, IO[AnyStr]],
    params_override: Optional[List[Dict[str, Any]]] = None):
    """
    Load a connection from a JSON file or string.
    """
    from azure.ai.ml.entities._load_functions import load_connection
    cogsvc_connection = None
    ml_connection = None
    try:
        ml_connection = load_connection(
            source=source,
            params_override=params_override,
        )
        # The azure.ai.ml._workspace._ai_workspaces.connection.Connection type maps to the
        # azure.mgmt.cognitiveservices.models.ConnectionPropertiesV2 credentialed subclass type.
        # We need to convert it to the latter type before sending it to the API.
    except Exception as e:
        raise FileOperationError(f"Failed to load connection from {source}: {e}",
                                 recommendation="Check the file path and format.")
    cogsvc_connection = _from_ml_connection(ml_connection)
    return cogsvc_connection

def _load_capability_host_from_file(
    source: Union[str, PathLike, IO[AnyStr]],
    params_override: Optional[List[Dict[str, Any]]] = None):
    """
    Load a capability host from a JSON file or string.
    """
    from azure.ai.ml.entities._load_functions import load_capability_host
    cogsvc_capability_host = None
    try:
        ml_capability_host = load_capability_host(
            source=source,
            params_override=params_override,
        )
        # The azure.ai.ml._workspace._ai_workspaces.capability_host.CapabilityHost type maps to the
        # azure.mgmt.cognitiveservices.models.CapabilityHostProperties type.
        # We need to convert it to the latter type before sending it to the API.
        cogsvc_capability_host = CapabilityHost(properties=CapabilityHostProperties(
            description=ml_capability_host.description,
            capability_host_kind=ml_capability_host.capability_host_kind,
            vector_store_connections=ml_capability_host.vector_store_connections,
            storage_connections=ml_capability_host.storage_connections,
            ai_services_connections=ml_capability_host.ai_services_connections,
        ))
    except Exception as e:
        raise FileOperationError(f"Failed to load capability host from {source}: {e}",
                                 recommendation="Check the file path and format.")
    return cogsvc_capability_host 

def _populate_capability_host(
        description=None, 
        capability_host_kind='Agents',
        vector_store_connections=None,
        storage_connections=None,
        ai_services_connections=None,
        file=None,

) -> CapabilityHost:
    ch_properties = CapabilityHostProperties()
    ch_properties.description = description
    ch_properties.capability_host_kind = capability_host_kind
    ch_properties.vector_store_connections = vector_store_connections
    ch_properties.storage_connections = storage_connections
    ch_properties.ai_services_connections = ai_services_connections
    capability_host = CapabilityHost(properties=ch_properties)
    if file is not None:
        params_override = [dict([x]) for x in capability_host.properties.as_dict()] 
        capability_host = _load_capability_host_from_file(
            source=file,
            params_override=params_override,
        )
    return capability_host

def _sdk_create_capability_host(
    client,
    resource_group_name: str,
    account_name: str,
    project_name: Optional[str],
    capability_host_name: str,
    capability_host: CapabilityHost,
    no_wait: bool = False,
):
    args = [resource_group_name, account_name]
    if project_name:
        args.append(project_name)
    args.append(capability_host_name)
    from azure.cli.core.util import sdk_no_wait
    return sdk_no_wait(no_wait,
                       client.begin_create_or_update,
                       *args,
                       capability_host)

def _create_capability_host(
        client,
        resource_group_name,
        account_name,
        capability_host_name,
        project_name=None,  # Optional for account-level capability hosts
        description=None,
        capability_host_kind='Agents',
        vector_store_connections=None,
        storage_connections=None,
        ai_services_connections=None,
        file=None,
        no_wait=False,
):
    capability_host = _populate_capability_host(
    description=description,
    capability_host_kind=capability_host_kind,
    vector_store_connections=vector_store_connections,
    storage_connections=storage_connections,
    ai_services_connections=ai_services_connections,
    file=file,
    )
    return _sdk_create_capability_host(
        client,
        resource_group_name,
        account_name,
        project_name,  # project_name is None for account-level capability hosts
        capability_host_name,
        capability_host,
        no_wait=no_wait,
    )

def account_capability_host_create(
        client,
        resource_group_name,
        account_name,
        capability_host_name,
        description=None,
        capability_host_kind='Agents',
        vector_store_connections=None,
        storage_connections=None,
        ai_services_connections=None,
        file=None,
        no_wait=False,
):
    """
    Create a capability host for Azure Cognitive Services account.
    """
    return _create_capability_host(
        client,
        resource_group_name,
        account_name,
        capability_host_name,
        description=description,
        capability_host_kind=capability_host_kind,
        vector_store_connections=vector_store_connections,
        storage_connections=storage_connections,
        ai_services_connections=ai_services_connections,
        file=file,
        no_wait=no_wait,
    )

def project_capability_host_create(
        client,
        resource_group_name,
        account_name,
        project_name,
        capability_host_name,
        description=None,
        capability_host_kind='Agents',
        vector_store_connections=None,
        storage_connections=None,
        ai_services_connections=None,
        file=None,
        no_wait=False,
):
    """
    Create a capability host for Azure Cognitive Services account or project.
    """
    return _create_capability_host(
        client,
        resource_group_name,
        account_name,
        capability_host_name,
        project_name=project_name,
        description=description,
        capability_host_kind=capability_host_kind,
        vector_store_connections=vector_store_connections,
        storage_connections=storage_connections,
        ai_services_connections=ai_services_connections,
        file=file,
        no_wait=no_wait,
    )

def project_create(
        client,
        resource_group_name,
        account_name,
        project_name,
        location,
        assign_identity=False,
        identity_type=None,
        user_assigned_identity=None,
        description=None,
        display_name=None,
        no_wait=False,
):
    """
    Create a project for Azure Cognitive Services account.
    """
    project = Project(properties=ProjectProperties())
    project.properties.description = description
    project.properties.display_name = display_name
    project.location = location
    # If the user specifies a User Assigned Identity, we need to set the identity type accordingly.
    if identity_type is None:
        if user_assigned_identity is not None:
            if assign_identity:
                project.identity = Identity(type=IdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED,
                                            user_assigned_identities={user_assigned_identity: {}})
            else:
                project.identity = Identity(type=IdentityType.USER_ASSIGNED,
                                            user_assigned_identities={user_assigned_identity: {}})
        else:
            project.identity = Identity(type=IdentityType.SYSTEM_ASSIGNED)
    return client.begin_create(resource_group_name, account_name, project_name, project, polling=no_wait)


def account_connection_create(
    client,
    resource_group_name,
    account_name,
    connection_name,
    file,
):
    """
    Create a connection for Azure Cognitive Services account.
    """
    account_connection_properties = _load_connection_from_file(source=file)
    account_connection = ConnectionPropertiesV2BasicResource(properties=account_connection_properties)

    return client.create(
        resource_group_name,
        account_name,
        connection_name,
        account_connection)

# This function is intended to be used with the 'generic_update_command' per
# https://github.com/Azure/azure-cli/blob/0b06b4f295766bcadaebdb7cf8fc05c7d6c9a5a8/doc/authoring_command_modules/authoring_commands.md#generic-update-commands
def account_connection_update(
    instance,
):
    """
    Update a connection for Azure Cognitive Services account.
    """
    account_connection = ConnectionUpdateContent(properties=instance.properties)
    return account_connection

def project_connection_create(
    client,
    resource_group_name,
    account_name,
    project_name,
    connection_name,
    file,
):
    """
    Create a connection for Azure Cognitive Services account.
    """
    project_connection_properties = _load_connection_from_file(source=file)
    project_connection = ConnectionPropertiesV2BasicResource(properties=project_connection_properties)
    return client.create(
        resource_group_name,
        account_name,
        project_name,
        connection_name,
        project_connection)

# This function is intended to be used with the 'generic_update_command' per
# https://github.com/Azure/azure-cli/blob/0b06b4f295766bcadaebdb7cf8fc05c7d6c9a5a8/doc/authoring_command_modules/authoring_commands.md#generic-update-commands
def project_connection_update(
    instance,
):
    """
    Update a connection for Azure Cognitive Services account.
    """
    print(f'Instance properties: {instance.properties}')
    print(f'Instance credentials: {instance.properties.credentials}')
    project_connection = ConnectionUpdateContent(properties=instance.properties)
    return project_connection
