import unittest
import os

from azure.cli.testsdk import ScenarioTest, ResourceGroupPreparer, StorageAccountPreparer

TEST_DIR = os.path.abspath(os.path.join(os.path.abspath(__file__), '..'))

class CognitiveServicesProjectCapabilityHostTests(ScenarioTest):

    INPUT_DATA_PATH=os.path.join(TEST_DIR, 'input_data', 'connections')

    # Reference: https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/ai-foundry/agents/concepts/capability-hosts.md
    
    def _create_search_service(self, service_name, resource_group, use_key=False,
                               sku='standard', partition_count=1, replica_count=1, assign_identity=False):
        self.kwargs.update({
            'searchsvc': service_name,
            'searchsku': sku,
            'searchpartitioncount': partition_count,
            'searchreplicacount': replica_count
        })
        ssvc = self.cmd('az search service create --search-service-name {searchsvc} --resource-group {rg} --sku {searchsku} --partition-count {searchpartitioncount} --replica-count {searchreplicacount}').get_output_in_json()

        ssvc_key = None
        if use_key:
            ssvc_key = self.cmd('az search admin-key show --service-name {searchsvc} --resource-group {rg} --query primaryKey -otsv').output
        return (ssvc, ssvc_key)
    
    def _delete_search_service(self):
        ret = self.cmd('az search service delete --name {searchsvc} --resource-group {rg}')
        self.assertEqual(ret.exit_code, 0)
        
    @ResourceGroupPreparer()
    @StorageAccountPreparer(parameter_name='storage_account', allow_shared_key_access=True)
    def test_project_capability_host(self, resource_group, storage_account_info):

        sname = self.create_random_name(prefix='cog', length=12)
        pname = self.create_random_name(prefix='prj', length=12)
        achname = self.create_random_name(prefix='ch', length=12)
        pchname = self.create_random_name(prefix='pch', length=12)
        srchname = self.create_random_name(prefix='srch', length=12)
        vecconnname = self.create_random_name(prefix='vecconn', length=16)
        stgname = storage_account_info[0]
        stgconnname = self.create_random_name(prefix='stgconn', length=16)
        vstgname = self.create_random_name(prefix='vstg', length=12)
        customdomain = self.create_random_name(prefix='csclitest', length=16)
        sa_key = storage_account_info[1].strip()
        
        self.kwargs.update({
            'sname': sname,
            'pname': pname,
            'achname': achname,
            'pchname': pchname,
            'stgname': stgname,
            'vstgname': vstgname,
            'stgconnname': stgconnname,
            'stgacctname': stgname,
            'stgacctkey': sa_key,
            'vecconnname': vecconnname,
            'kind': 'AIServices',
            'sku': 'S0',
            'location': 'eastus',
            'projdisplayname': 'CLI Test Project',
            'customdomain': customdomain
        })

        # test to create cognitive services account
        self.cmd('az cognitiveservices account create -n {sname} -g {rg} --kind {kind} --sku {sku} -l {location} --yes --assign-identity --allow-project-management true --custom-domain {customdomain}',
                 checks=[self.check('name', '{sname}'),
                         self.check('location', '{location}'),
                         self.check('sku.name', '{sku}'),
                         self.check('properties.allowProjectManagement', True),
                         self.check('properties.customSubDomainName', '{customdomain}')])

        ret = self.cmd('az cognitiveservices account capability-host create -n {sname} -g {rg} --capability-host-name {achname}',
                           checks=[self.check('properties.provisioningState', 'Succeeded')])
        self.assertEqual(ret.exit_code, 0)

        ret = self.cmd('az cognitiveservices account project create -n {sname} -g {rg} --project-name {pname} --location {location} --assign-identity --display-name "{projdisplayname}"',
                            checks=[self.check('properties.provisioningState', 'Succeeded'),
                                    self.check('properties.displayName', '{projdisplayname}')])
        self.assertEqual(ret.exit_code, 0)
        
        # Create the required connections - they need to exist for the capability-host to be successfully created
        ret = self.cmd('az storage container create -n test --account-name {stgacctname} --account-key {stgacctkey}',
                                checks=[self.check('created', True)])
        self.assertEqual(ret.exit_code, 0)
        container_list = self.cmd('az storage container list --account-name {stgacctname} --account-key {stgacctkey} --query "[].name"').get_output_in_json()
        self.assertTrue(len(container_list) > 0)
        self.assertTrue(container_list[0] == 'test')
                
        stgacctinfo = self.cmd('az storage account show --name {stgacctname} --resource-group {rg}').get_output_in_json()

        # Assign 'Storage Blob Data Contributor' role to project System Assigned Identity
        project_sai = self.cmd('az cognitiveservices account project show -n {sname} -g {rg} --project-name {pname} --query identity.principalId -otsv').output
        self.kwargs.update({
            'project_sai': project_sai,
            'stgacctid': stgacctinfo['id']
        })
        ret = self.cmd('az role assignment create --assignee {project_sai} --role "Storage Blob Data Contributor" --scope {stgacctid}')
        self.assertEqual(ret.exit_code, 0)

        import tempfile
        import yaml
        with tempfile.NamedTemporaryFile(delete_on_close=False, delete=False, prefix="stgconn") as tmpfile:
            connection_file_data = {
                'name': stgconnname,
                'type': 'azure_blob',
                'url': f"{stgacctinfo['primaryEndpoints']['blob']}test",
                'credentials': {
                    'type': 'account_key',
                    'account_key': sa_key
                },
                'metadata': {
                    'ApiType': 'Azure',
                    'ResourceId': stgacctinfo['id']
                },
                'container_name': 'test',
                'account_name': stgname
            }
            _ = tmpfile.write(yaml.dump(connection_file_data).encode())
            self.kwargs.update({
                'stgconnfile': tmpfile.name
            })
            tmpfile.close()

            ret = self.cmd(command='az cognitiveservices account project connection create -n {sname} -g {rg} --project-name {pname} --connection-name {stgconnname} --file {stgconnfile}',
                            checks=[
                                self.check('properties.authType', 'AccountKey'),
                                self.check('properties.category', "AzureStorageAccount"),
                                self.check('name', '{stgconnname}')])
            self.assertEqual(ret.exit_code, 0)

        search_service_info = self._create_search_service(service_name=srchname, resource_group=resource_group, use_key=True)
        with tempfile.NamedTemporaryFile(delete_on_close=False, delete=False, prefix="srchconn") as tmpfile:
            connection_file_data = {
                'name': vecconnname,
                'type': 'azure_ai_search',
                'endpoint': f'https://{search_service_info[0]}.search.windows.net/',
                'credentials': {
                    'type': 'api_key',
                    'key': search_service_info[1]
                }
            }
            _ = tmpfile.write(yaml.dump(connection_file_data).encode())
            self.kwargs.update({
                'vecconnfile': tmpfile.name
            })
            tmpfile.close()
        
            ret = self.cmd('az cognitiveservices account project connection create -n {sname} -g {rg} --project-name {pname} --connection-name {vecconnname} --file {vecconnfile}',
                            checks=[
                                self.check('properties.authType', 'ApiKey'),
                                self.check('properties.category', "CognitiveSearch"),
                                self.check('name', '{vecconnname}')])
            self.assertEqual(ret.exit_code, 0)

        caphost = self.cmd('az cognitiveservices account project capability-host create -n {sname} -g {rg} --project-name {pname} --capability-host-name {pchname} --storage-connections "{stgconnname}" --vector-store-connections "{vecconnname}"',
                           checks=[self.check('properties.provisioningState', 'Succeeded')]).get_output_in_json()
        self.assertEqual(caphost['properties']['capabilityHostKind'], 'Agents')
        self.assertTrue(len(caphost['properties']['storageConnections']) > 0)
        self.assertTrue(len(caphost['properties']['vectorStoreConnections']) > 0)

        ret= self.cmd('az cognitiveservices account project capability-host show -n {sname} -g {rg} --project-name {pname} --capability-host-name {pchname}')
        self.assertEqual(ret.exit_code, 0)
        
        # delete the cognitive services account
        ret= self.cmd('az cognitiveservices account project capability-host delete -n {sname} -g {rg} --project-name {pname} --capability-host-name {pchname}')
        self.assertEqual(ret.exit_code, 0)

        ret = self.cmd('az cognitiveservices account project connection delete -n {sname} -g {rg} --project-name {pname} --connection-name {stgconnname}')
        self.assertEqual(ret.exit_code, 0)

        ret = self.cmd('az cognitiveservices account project connection delete -n {sname} -g {rg} --project-name {pname} --connection-name {vecconnname}')
        self.assertEqual(ret.exit_code, 0)
        
        ret= self.cmd('az cognitiveservices account project delete -n {sname} -g {rg} --project-name {pname}')
        self.assertEqual(ret.exit_code, 0)
        
        ret= self.cmd('az cognitiveservices account capability-host delete -n {sname} -g {rg} --capability-host-name {achname}')
        self.assertEqual(ret.exit_code, 0)
        
        self._delete_search_service()
        
        ret = self.cmd('az cognitiveservices account delete -n {sname} -g {rg}')
        self.assertEqual(ret.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
