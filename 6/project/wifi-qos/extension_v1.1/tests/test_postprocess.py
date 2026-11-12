from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
try:
    import postprocess
except ImportError:
    postprocess=None


class StatisticsContract(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(postprocess,'offline analysis missing')

    def test_run_means_have_sample_sd_and_keep_replicate_count(self):
        result=postprocess.describe([1,2,3])
        self.assertEqual(result,{'n':3,'mean':2,'sample_sd':1})

    def test_missing_delay_does_not_become_zero(self):
        result=postprocess.describe([None,None,None])
        self.assertEqual(result,{'n':0,'mean':None,'sample_sd':None})

    def test_high_variation_requests_whole_comparison_to_five(self):
        rows=[]
        for mode,values in [('baseline',[1,1,1]),('qos',[1,2,3]),('fq_codel',[1,1,1])]:
            for i,v in enumerate(values,1):rows.append(dict(experiment='E1',mode=mode,workload='static',rt_kbit=600,
                buffer_bytes=32768,repeat=i,udp_jitter_ms=v,udp_loss_percent=0))
        extra=postprocess.supplement_manifest(rows)
        self.assertEqual(len(extra),24)
        self.assertEqual({x['mode'] for x in extra},{'baseline','qos','fq_codel'})
        self.assertEqual({x['repeat'] for x in extra},{4,5})
        self.assertEqual([x['repeat'] for x in extra],[4]*12+[5]*12)

    def test_supplement_trigger_survives_repeat_four(self):
        rows=[]
        for mode,values in [('baseline',[1,1,1]),('qos',[.65,1,1,(.65+1+1)/3]),('fq_codel',[1,1,1])]:
            for i,v in enumerate(values,1):rows.append(dict(experiment='E1',mode=mode,workload='static',rt_kbit=600,
                buffer_bytes=32768,repeat=i,udp_jitter_ms=v,udp_loss_percent=0))
        extra=postprocess.supplement_manifest(rows)
        self.assertTrue(any(x['mode']=='qos' and x['rt_kbit']==600 and x['buffer_bytes']==32768 and x['repeat']==5 for x in extra))
        self.assertFalse(any(x['mode']=='qos' and x['rt_kbit']==600 and x['buffer_bytes']==32768 and x['repeat']==4 for x in extra))

    def test_final_source_uses_audited_records_instead_of_compact_pass(self):
        import tempfile,json
        self.assertTrue(hasattr(postprocess,'load_records'),'canonical source loader missing')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'results';out.mkdir()
            (out/'compact.json').write_text(json.dumps({'runs':[{'id':'unaudited'}]}))
            (out/'audit.json').write_text(json.dumps({'integrity_passed':True,'checks_passed':True,'records':[{'id':'verified'}]}))
            records,status=postprocess.load_records(Path(tmp))
            self.assertEqual(records,[{'id':'verified'}])
            self.assertEqual(status,'FINAL')

    def test_missing_delay_contributing_count_is_visible(self):
        from write_report import show
        self.assertIn('2/3',show([1,None,3]))

    def test_queue_summary_excludes_warmup_and_tail(self):
        self.assertTrue(hasattr(postprocess,'steady_queue_samples'),'steady queue selection missing')
        record={'config':{'udp_start_lower_ns':0,'warmup':10,'seconds':60},
                'resources':{'queue_series':[{'mono_ns':int(t*1e9)} for t in [9,10,59.5,60,62]]}}
        samples=postprocess.steady_queue_samples(record)
        self.assertEqual([s['mono_ns'] for s in samples],[10_000_000_000,59_500_000_000])

    def test_phase_table_does_not_copy_high_phase_loss_to_low_phase(self):
        config=dict(id='x',experiment='E3',mode='qos',rt_kbit=600,buffer_bytes=32768,workload='dynamic',repeat=1,seconds=90,kind='formal')
        phases=[dict(phase=i,loss_percent=loss,received_mbps=.3,delay_p95_ms=2,on_time_percent=100-loss,
                     tcp={'received_mbps':1,'analyzed_seconds':29,'window_coverage_fraction':.97}) for i,loss in enumerate([0,40,0])]
        rows,table=postprocess.flatten([{'config':config,'status':'PASS','metrics':{'phases':phases,'rtt':{'mean_ms':2,'p95_ms':3},'recovery_seconds':0}}])
        self.assertEqual([x['udp_loss_percent'] for x in table],[0,40,0])


if __name__=='__main__':unittest.main()
