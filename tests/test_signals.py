import io
import os
import shutil
import tempfile
import unittest
import zipfile

from _load import load

signals = load("trader-replay", "signals")


def form345_zip():
    sub = ("ACCESSION_NUMBER\tFILING_DATE\tPERIOD_OF_REPORT\tDOCUMENT_TYPE\tISSUERCIK\tISSUERNAME\tISSUERTRADINGSYMBOL\n"
           "A1\t03-MAR-2023\t01-MAR-2023\t4\t1\tAcme\tACME\n"
           "A2\t04-MAR-2023\t02-MAR-2023\t4\t1\tAcme\tACME\n"
           "A3\t05-MAR-2023\t02-MAR-2023\t4\t2\tBerk\tBRK.B\n"
           "A4\t05-MAR-2023\t02-MAR-2023\t3\t3\tNew\tNEWCO\n")
    own = ("ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
           "A1\t900\tJane CEO\tOfficer\tCEO\nA2\t901\tBob Director\tDirector\t\nA3\t902\tFund\tTenPercentOwner\t\n"
           "A4\t903\tX\tDirector\t\n")
    trans = ("ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tSECURITY_TITLE\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
             "TRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
             "A1\t1\tCommon\t01-MAR-2023\tP\t1000\t10.5\tA\n"
             "A1\t2\tCommon\t01-MAR-2023\tS\t50\t11\tD\n"     # a sale: not a purchase
             "A2\t3\tCommon\t02-MAR-2023\tP\t200\t10\tA\n"
             "A3\t4\tClass B\t02-MAR-2023\tP\t10\t400\tA\n"
             "A3\t5\tClass B\t02-MAR-2023\tA\t10\t0\tA\n"     # an award, not bought on the market
             "A4\t6\tCommon\t02-MAR-2023\tP\t10\t5\tA\n")     # a Form 3: not a transaction report
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2023q1_form345/SUBMISSION.tsv", sub)
        z.writestr("2023q1_form345/REPORTINGOWNER.tsv", own)
        z.writestr("2023q1_form345/NONDERIV_TRANS.tsv", trans)
    return buf.getvalue()


class Insiders(unittest.TestCase):
    def test_parse_keeps_open_market_purchases_only(self):
        rows = signals.parse_form345(form345_zip())
        self.assertEqual(rows, [["2023-03-03", "ACME", "900", "officer", 1000.0, 10.5, 10500.0],
                                ["2023-03-04", "ACME", "901", "director", 200.0, 10.0, 2000.0],
                                ["2023-03-05", "BRK-B", "902", "10% owner", 10.0, 400.0, 4000.0]])

    def test_build_and_point_in_time_queries(self):
        doc = signals.build_insiders(["2023q1"], "test ua", log=lambda m: None, http=lambda url: form345_zip())
        self.assertEqual(len(doc["rows"]), 3)
        self.assertIn("2023q1_form345.zip", signals.SEC_345 % "2023q1")
        s = signals.Signals(insiders=doc)
        self.assertEqual(s.insider_buys("2023-03-03")["ACME"], {"insiders": 1, "officers": 1, "value": 10500.0})
        self.assertEqual(s.insider_buys("2023-03-04")["ACME"]["insiders"], 2)
        self.assertNotIn("BRK-B", s.insider_buys("2023-03-04"))  # filed the next day: not known yet
        self.assertEqual(s.insider_buys("2023-06-01"), {})          # older than 60 days
        self.assertEqual(signals.quarters("2022q3-2023q2"), ["2022q3", "2022q4", "2023q1", "2023q2"])
        self.assertEqual([signals.iso(x) for x in ("31-MAR-2023", "2023-03-31", "03/31/2023", "junk")],
                         ["2023-03-31"] * 3 + [None])

    def test_save_and_load(self):
        d = tempfile.mkdtemp()
        try:
            doc = signals.build_insiders(["2023q1"], "ua", log=lambda m: None, http=lambda url: form345_zip())
            signals.write(os.path.join(d, "insiders.json.gz"), doc)
            s = signals.Signals.load(d)
        finally:
            shutil.rmtree(d)
        self.assertTrue(s)
        self.assertEqual(len(s.insiders), 3)


class Congress(unittest.TestCase):
    def test_buys_need_the_filing_to_be_public_and_net_buying(self):
        doc = {"rows": [
            ["2023-01-10", "Ann A", "NVDA", "buy", 1001, 15000, "2022-12-20", "self"],
            ["2023-01-12", "Ben B", "NVDA", "buy", 15001, 50000, "2023-01-05", "spouse"],
            ["2023-01-12", "Ann A", "NVDA", "buy", 1001, 15000, "2023-01-06", "self"],
            ["2023-01-15", "Cy C", "XOM", "buy", 1001, 15000, "2023-01-02", "self"],
            ["2023-01-16", "Di D", "XOM", "sell", 1001, 15000, "2023-01-03", "self"],
            ["2023-01-16", "Ed E", "XOM", "sell", 1001, 15000, "2023-01-03", "self"]]}
        s = signals.Signals(congress=doc)
        self.assertEqual(s.congress_buys("2023-01-11"), {"NVDA": {"members": 1, "buys": 1, "sells": 0, "low": 1001}})
        nv = s.congress_buys("2023-01-20")
        self.assertEqual(nv["NVDA"]["members"], 2)  # two different members
        self.assertNotIn("XOM", nv)                  # more sells than buys
        self.assertEqual(s.congress_buys("2023-06-01"), {})


if __name__ == "__main__":
    unittest.main()
