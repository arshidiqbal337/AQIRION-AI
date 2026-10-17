import unittest
from engine import chunks,retrieve,analyze
class EngineTests(unittest.TestCase):
    def setUp(self):self.docs=[{'id':1,'name':'rag.txt','text':'Retrieval augmented generation uses document retrieval to provide context for language model answers. It can improve source attribution.'}]
    def test_chunks(self):self.assertTrue(chunks('hello world'))
    def test_retrieve(self):self.assertEqual(retrieve('document retrieval',self.docs)[0]['source'],'rag.txt')
    def test_grounded(self):self.assertEqual(analyze('document retrieval',self.docs)['status'],'evidence_found')
    def test_no_evidence(self):self.assertEqual(analyze('quantum banana xylophone',self.docs)['status'],'insufficient_evidence')
    def test_empty(self):self.assertEqual(analyze('test',[])['evidence'],[])
if __name__=='__main__':unittest.main()
