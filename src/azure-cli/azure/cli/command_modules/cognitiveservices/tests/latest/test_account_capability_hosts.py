import unittest

from azure.cli.testsdk import ScenarioTest, ResourceGroupPreparer

class CognitiveServicesAccountCapabilityHostTests(ScenarioTest):

    @ResourceGroupPreparer()
    def test_account_capability_host(self, resource_group):

        sname = self.create_random_name(prefix='cog', length=12)
        chname = self.create_random_name(prefix='ch', length=12)
        stgname = self.create_random_name(prefix='stg', length=12)
        vstgname = self.create_random_name(prefix='vstg', length=12)
        
        self.kwargs.update({
            'sname': sname,
            'chname': chname,
            'stgname': stgname,
            'vstgname': vstgname,
            'kind': 'AIServices',
            'sku': 'S0',
            'location': 'eastus',
        })

        # test to create cognitive services account
        self.cmd('az cognitiveservices account create -n {sname} -g {rg} --kind {kind} --sku {sku} -l {location} --yes --assign-identity --allow-project-management true',
                 checks=[self.check('name', '{sname}'),
                         self.check('location', '{location}'),
                         self.check('sku.name', '{sku}'),
                         self.check('properties.allowProjectManagement', True)])

        caphost = self.cmd('az cognitiveservices account capability-host create -n {sname} -g {rg} --capability-host-name {chname} --storage-connections {stgname} --vector-store-connections {vstgname}',
                           checks=[self.check('properties.provisioningState', 'Succeeded')]).get_output_in_json()
        self.assertEqual(caphost['properties']['capabilityHostKind'], 'Agents')
        self.assertTrue(len(caphost['properties']['storageConnections']) > 0)
        self.assertTrue(len(caphost['properties']['vectorStoreConnections']) > 0)

        ret= self.cmd('az cognitiveservices account capability-host show -n {sname} -g {rg} --capability-host-name {chname}')
        self.assertEqual(ret.exit_code, 0)
        # delete the cognitive services account
        ret= self.cmd('az cognitiveservices account capability-host delete -n {sname} -g {rg} --capability-host-name {chname}')
        self.assertEqual(ret.exit_code, 0)
        ret = self.cmd('az cognitiveservices account delete -n {sname} -g {rg}')
        self.assertEqual(ret.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
