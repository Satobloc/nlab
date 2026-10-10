"""Regression and isolation tests for standalone nLab-only Mersearch."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS=Path(__file__).resolve().parents[1]
ROOT=TOOLS.parent
sys.path.insert(0,str(TOOLS))
import mersearch as S
import mersearch_core as C
import mersearch_math as M
import mersearch_math_genealogy as G

FIX="tools/tests/fixtures"


def cli(*args:str, success:bool=True):
    cmd=[sys.executable,str(TOOLS/"mersearch.py"),*args]
    result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=75)
    if success and result.returncode:
        raise AssertionError("CLI failed: "+result.stderr+"\nSTDOUT: "+result.stdout)
    return result


class SingleRepositorySafety(unittest.TestCase):
    def test_self_description_exposes_repo_only_and_all_modes(self):
        r=cli("--capabilities")
        meta=json.loads(r.stdout)
        self.assertEqual(meta["repository"],"Satobloc/nlab")
        self.assertTrue(meta["single_repository_only"])
        self.assertFalse(meta["network_access"])
        self.assertFalse(meta["database_access"])
        self.assertFalse(meta["wiki_pages_included"])
        self.assertIn("equiv",meta["fields"])
        self.assertIn("--math-genealogy",meta["modes"])

    def test_no_external_paths_accepted(self):
        for path in ("../HsH","/tmp","../../","tools/../other","C:\\external","/"):
            if path.startswith("C:"):
                # Backslash paths are not special on POSIX; no need to claim
                # Windows-drive sanitization in a Linux CI runner.
                continue
            with self.subTest(scope=path):
                self.assertNotEqual(cli("--coverage","--scope",path,success=False).returncode,0)

    def test_output_must_stay_inside_ignored_nlab_results(self):
        for dest in ("out","../../out","/tmp/elsewhere",".git/metadata"):
            self.assertNotEqual(cli("--scope",FIX,"--query","functor","--out",dest,success=False).returncode,0)

    def test_scanner_skips_vendor_by_default(self):
        scope=S.root_relative("vendor",must_exist=True)
        summary=S.Counter()
        files=list(S.scan_files([scope],{v.casefold() for v in S.EXCLUDES},100_000,summary))
        self.assertEqual(files,[])
        self.assertGreater(summary["excluded_paths"],0)

    def test_symlink_target_outside_repo_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"tools"/"tests"/"fixtures") as tmp:
            path=Path(tmp)/"external"
            try:path.symlink_to("/tmp",target_is_directory=True)
            except (NotImplementedError,OSError):self.skipTest("symlink not supported")
            with self.assertRaisesRegex(ValueError,"symbolic"):
                S.root_relative(path.relative_to(ROOT).as_posix(),must_exist=True)
            summary=S.Counter()
            self.assertEqual(list(S.scan_files([path],set(),100_000,summary)),[])

    def test_no_imported_data_from_another_repo(self):
        for filename in ("mersearch.py","mersearch_core.py","mersearch_math.py",
                         "mersearch_math_genealogy.py"):
            script=(TOOLS/filename).read_text(encoding="utf-8")
            for marker in ("SAT_THEORY_ARCHIVE_2023-25","Satobloc/HsH","Satobloc/HSH_RESOURCES",
                           "git clone","requests.get(","httpx.get("):
                self.assertNotIn(marker,script)


class SearchAndFormats(unittest.TestCase):
    def run_query(self,*query_args):
        with tempfile.TemporaryDirectory(dir=ROOT/".mersearch") as directory:
            out=Path(directory).relative_to(ROOT).as_posix()
            proc=cli("--scope",FIX,"--out",out,*query_args)
            response=json.loads((Path(directory)/"SEARCH_RESULTS.json").read_text(encoding="utf-8"))
            self.assertEqual(response["repository"],"Satobloc/nlab")
            self.assertEqual(response["scope"],"single-repository-local-only")
            self.assertEqual(len(response["hits"]),response["coverage"]["returned_hits"])
            self.assertTrue(all(h["repository"]=="Satobloc/nlab" for h in response["hits"]))
            self.assertTrue(all("github.com/Satobloc/nlab/" in h["source_url"]
                                for h in response["hits"]))
            for suffix in ("json","jsonl","md","csv"):
                self.assertTrue((Path(directory)/("SEARCH_RESULTS."+suffix)).is_file())
            return response

    def test_actual_nlab_readme_is_searchable(self):
        p=cli("--scope","README.md","--expr",'"nLab software"')
        result=json.loads(p.stdout)
        self.assertGreater(result["results_before_limit"],0)

    def test_boolean_phrase_proximity_and_filters(self):
        r=self.run_query("--expr",'"functor" NEAR/5 "category"')
        self.assertGreater(r["coverage"]["total_results_before_limit"],0)
        self.assertTrue(any("mersearch_text.md" in h["path"] for h in r["hits"]))
        r=self.run_query("--expr",'("revision" AND ext:rb) OR "alpha beta gamma"')
        self.assertGreaterEqual(r["coverage"]["total_results_before_limit"],2)
        r=self.run_query("--expr","functor AND NOT ext:rb","--result-mode","files")
        self.assertTrue(all(not h["path"].endswith(".rb") for h in r["hits"]))

    def test_json_inside_txt_is_structured_with_time_and_role(self):
        r=self.run_query("--expr",'role:user AND date:2025-06-15')
        # Unix date fixture belongs to 2025-06-15 UTC.
        self.assertEqual(r["coverage"]["total_results_before_limit"],1)
        h=r["hits"][0]
        self.assertEqual(h["kind"],"conversation-message")
        self.assertEqual(h["role"],"user")
        self.assertEqual(h["message_id"],"m1")
        self.assertTrue(h["source_sha256"])
        self.assertIn("2025-06-15",h["timestamp"])

    def test_reported_total_is_not_limited_count(self):
        r=self.run_query("--query","category","--limit","1")
        self.assertEqual(len(r["hits"]),1)
        self.assertGreaterEqual(r["coverage"]["total_results_before_limit"],2)
        r=self.run_query("--query","category","--result-mode","files")
        self.assertEqual(len({h["path"] for h in r["hits"]}),len(r["hits"]))

    def test_local_coverage_reports_missing_wiki_pages(self):
        p=cli("--coverage","--scope",FIX)
        data=json.loads(p.stdout)
        self.assertFalse(data["coverage"]["wiki_database_included"])
        self.assertGreaterEqual(data["coverage"]["files_scanned"],3)

    @unittest.skipUnless(M.S is not None,"SymPy not installed")
    def test_symbolic_equivalence_and_negative_controls(self):
        r=self.run_query("--expr",'equiv:"a+b=c"')
        self.assertGreaterEqual(len(r["hits"]),1)
        evidence=[e for h in r["hits"] for e in h["math_evidence"]]
        self.assertTrue(any(x["classification"]=="ALGEBRAICALLY_EQUIVALENT_POLYNOMIAL"
                            for x in evidence))
        negative=self.run_query("--expr",'equiv:"x=0.251"')
        self.assertEqual(negative["coverage"]["total_results_before_limit"],0)

    @unittest.skipUnless(M.S is not None,"SymPy not installed")
    def test_numeric_consistency_is_not_equivalence(self):
        r=self.run_query("--expr",'value:"x=0.25;atol=0.002"')
        self.assertTrue(any(e["classification"]=="NUMERICALLY_CONSISTENT"
                            for h in r["hits"] for e in h["math_evidence"]))

    @unittest.skipUnless(M.S is not None,"SymPy not installed")
    def test_local_standalone_genealogy_inventory(self):
        with tempfile.TemporaryDirectory(dir=ROOT/".mersearch") as directory:
            out=Path(directory).relative_to(ROOT).as_posix()
            cli("--scope",FIX,"--inventory-only","--math-genealogy","--out",out)
            graph=json.loads((Path(directory)/"MATH_GENEALOGY.json").read_text(encoding="utf-8"))
            results=json.loads((Path(directory)/"SEARCH_RESULTS.json").read_text(encoding="utf-8"))
            self.assertGreater(len(graph["nodes"]),0)
            self.assertEqual(results["hits"],[])
            self.assertEqual(graph["coverage"]["indexed_repositories"],["Satobloc/nlab"])
            self.assertTrue(all(n["repository"]=="Satobloc/nlab" for n in graph["nodes"]))
            self.assertTrue(all("Satobloc/nlab/" in n["source_url"] for n in graph["nodes"]))


if __name__=="__main__":
    (ROOT/".mersearch").mkdir(exist_ok=True)
    unittest.main()
