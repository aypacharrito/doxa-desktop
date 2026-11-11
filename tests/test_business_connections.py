import json
import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch,Mock
from forgemind.business_connections import BusinessConnections,vyra_report,status_text

class BusinessTests(unittest.TestCase):
    def test_stale_report_does_not_claim_connection(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,LOCALAPPDATA=folder):
            p=Path(folder)/'Programs/VYRA/clips-worker/.local/growth-latest.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'created_at':(datetime.now(timezone.utc)-timedelta(days=3)).isoformat(),'channels':{'youtube':{}}}))
            self.assertFalse(vyra_report()['connected'])

    def test_health_is_not_workspace_access(self):
        with tempfile.TemporaryDirectory() as folder:
            response=Mock();response.json.return_value={'ready':True,'checks':{},'background':{'lastRunAt':None}}
            with patch('forgemind.business_connections.requests.get',return_value=response) as get,patch('forgemind.business_connections.vyra_report',return_value={'connected':False}):
                result=BusinessConnections(folder).refresh()
            self.assertTrue(result['pacifica']['service_reachable']);self.assertFalse(result['pacifica']['workspace_connected'])
            self.assertIn('workspace not connected',status_text(result))
            self.assertEqual(get.call_args.args[0],'https://crm.example.com/api/health')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_expired_workspace_does_not_claim_current_access(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'pacifica-summary.json').write_text(json.dumps({'checked_at':(datetime.now(timezone.utc)-timedelta(days=4)).isoformat(),'contacts':20}))
            with patch('forgemind.business_connections.requests.get',side_effect=OSError),patch('forgemind.business_connections.vyra_report',return_value={}):
                result=BusinessConnections(folder).refresh()
            self.assertFalse(result['pacifica']['workspace_connected'])
