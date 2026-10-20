import json
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


IDX = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Last Data Received:    Apr 15, 2026

Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
3           NEW CO                                                        111         20260415    edgar/data/111/0000111-26-000001.txt
4           ACME CORP                                                     222         20260415    edgar/data/222/0000222-26-000009.txt
4           SMITH JANE                                                    900         20260415    edgar/data/222/0000222-26-000009.txt
4           OTHER INC                                                     333         20260415    edgar/data/333/0000333-26-000004.txt
"""
FORM4 = """<SEC-DOCUMENT>
<XML>
<?xml version="1.0"?>
<ownershipDocument>
 <documentType>4</documentType>
 <issuer><issuerCik>222</issuerCik><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
 <reportingOwner>
  <reportingOwnerId><rptOwnerCik>900</rptOwnerCik></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer></reportingOwnerRelationship>
 </reportingOwner>
 <nonDerivativeTable>
  <nonDerivativeTransaction>
   <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>1000</value></transactionShares>
    <transactionPricePerShare><value>12.5</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  </nonDerivativeTransaction>
  <nonDerivativeTransaction>
   <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>10</value></transactionShares>
    <transactionPricePerShare><value>13</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
  </nonDerivativeTransaction>
 </nonDerivativeTable>
</ownershipDocument>
</XML>
</SEC-DOCUMENT>"""


class InsidersRecent(unittest.TestCase):
    def test_daily_index_and_form4(self):
        idx = signals.parse_daily_index(IDX)
        self.assertEqual(idx[1], ("4", "ACME CORP", "222", "2026-04-15", "edgar/data/222/0000222-26-000009.txt"))
        self.assertEqual(signals.parse_form4(FORM4, "2026-04-15"),
                         [["2026-04-15", "ACME", "900", "officer", 1000.0, 12.5, 12500.0]])
        self.assertEqual(signals.parse_form4("no xml here", "2026-04-15"), [])

    def test_build_reads_each_filing_once_and_only_wanted_issuers(self):
        calls = []

        def http(url):
            calls.append(url)
            if url.endswith("company_tickers.json"):
                return '{"0": {"cik_str": 222, "ticker": "ACME"}, "1": {"cik_str": 333, "ticker": "OTH"}}'
            if "form.20260415" in url:
                return IDX
            if "0000222-26-000009" in url:
                return FORM4
            raise signals.urllib.error.HTTPError(url, 404, "nf", None, None)
        doc = signals.build_insiders_recent("2026-04-15", "2026-04-15", "ua", tickers=["ACME"], log=lambda m: None,
                                            http=http, pause=0)
        self.assertEqual(len(doc["rows"]), 1)
        self.assertEqual(sum(1 for c in calls if "0000222-26-000009" in c), 1)  # listed twice, read once
        self.assertFalse(any("0000333" in c for c in calls))                      # not a wanted issuer

    def test_recent_rows_fill_after_the_bulk_files(self):
        d = tempfile.mkdtemp()
        try:
            signals.write(os.path.join(d, "insiders.json.gz"), {"rows": [["2026-03-30", "ACME", "1", "officer", 1, 1, 1]]})
            signals.write(os.path.join(d, "insiders_recent.json.gz"), {"rows": [
                ["2026-03-30", "ACME", "1", "officer", 1, 1, 1],          # already in the bulk files
                ["2026-04-15", "ACME", "900", "officer", 1000, 12.5, 12500]]})
            s = signals.Signals.load(d)
        finally:
            shutil.rmtree(d)
        self.assertEqual([r[0] for r in s.insiders], ["2026-03-30", "2026-04-15"])


class Events(unittest.TestCase):
    def test_8k_rows_are_dated_to_when_the_market_could_act(self):
        recent = {"filings": {"recent": {
            "form": ["8-K", "10-Q", "8-K", "8-K/A", "8-K"],
            "filingDate": ["2026-07-30", "2026-07-30", "2026-07-29", "2026-05-01", "2014-03-03"],
            "acceptanceDateTime": ["2026-07-30T16:05:11.000Z", "2026-07-30T09:00:00.000Z", "2026-07-29T08:30:00.000Z",
                                   "2026-05-01T12:00:00.000Z", "2014-03-03T12:00:00.000Z"],
            "items": ["2.02,9.01", "", "5.02", "8.01", "2.02"]},
            "files": [{"name": "CIK0000000222-submissions-001.json", "filingTo": "2016-01-01"}]}}
        older = {"form": ["8-K"], "filingDate": ["2015-06-01"], "acceptanceDateTime": ["2015-06-01T17:00:00.000Z"],
                 "items": ["1.01"]}

        def http(url):
            if url.endswith("company_tickers.json"):
                return '{"0": {"cik_str": 222, "ticker": "ACME"}}'
            return json.dumps(older if "-submissions-001" in url else recent)
        doc = signals.build_events(["ACME", "GONE"], "ua", log=lambda m: None, http=http, pause=0)
        self.assertEqual(doc["rows"], [
            ["2015-06-02", "ACME", "1.01", "2015-06-01"],          # after 4 p.m.: the next day
            ["2026-05-01", "ACME", "8.01", "2026-05-01"],
            ["2026-07-29", "ACME", "5.02", "2026-07-29"],
            ["2026-07-31", "ACME", "2.02,9.01", "2026-07-30"]])    # earnings after the close: tradable next day
        self.assertEqual(doc["stats"]["no_cik"], 1)
        s = signals.Signals(events=doc)
        self.assertEqual(s.news("2026-07-31", 3), {"ACME": ["2026-07-29", "2026-07-31"]})
        self.assertEqual(s.news("2026-07-30", 3, item="2.02"), {})  # not tradable until the 31st
        self.assertEqual(s.news("2026-07-31", 3, item="2.02"), {"ACME": ["2026-07-31"]})


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": "x", "fy": 2023, "fp": "Q"}


class Eps(unittest.TestCase):
    def doc(self):
        return {"units": {"USD/shares": [
            fact("2022-01-01", "2022-03-31", 1.0, "2022-05-01"), fact("2022-04-01", "2022-06-30", 1.0, "2022-08-01"),
            fact("2022-07-01", "2022-09-30", 1.0, "2022-11-01"),
            fact("2022-01-01", "2022-12-31", 5.0, "2023-02-15", "10-K"),                # Q4 = 5 - 3
            fact("2023-01-01", "2023-03-31", 1.5, "2023-05-01"),
            fact("2022-01-01", "2022-03-31", 0.7, "2023-05-01"),                        # restated later: ignored
            fact("2023-01-01", "2023-06-30", 3.0, "2023-08-01"),                        # six months: ignored
            fact("2023-04-01", "2023-06-30", 0.9, "2023-08-01", "8-K")]}}               # not a 10-Q or 10-K

    def test_quarters_first_filed_and_the_fourth_from_the_year(self):
        rows = signals.parse_concept(self.doc(), "ACME")
        self.assertEqual(rows, [["2022-05-01", "ACME", "2022-03-31", 1.0], ["2022-08-01", "ACME", "2022-06-30", 1.0],
                                ["2022-11-01", "ACME", "2022-09-30", 1.0], ["2023-02-15", "ACME", "2022-12-31", 2.0],
                                ["2023-05-01", "ACME", "2023-03-31", 1.5]])

    def test_surprise_is_point_in_time(self):
        rows = signals.parse_concept(self.doc(), "ACME")
        s = signals.Signals(eps={"rows": rows})
        self.assertIsNone(s.eps_surprise("ACME", "2023-04-30"))   # Q4 2022 has no year-ago quarter on file
        e = s.eps_surprise("ACME", "2023-05-01")                   # the day the Q1 2023 10-Q was filed
        self.assertEqual((e["end"], e["eps"], e["prior"], e["change"]), ("2023-03-31", 1.5, 1.0, 0.5))
        self.assertIsNone(e["sue"])                                 # too little history to judge the size
        self.assertIsNone(s.eps_surprise("ACME", "2023-12-01"))   # stale: no newer quarter filed
        self.assertIsNone(s.eps_surprise("ZZZ", "2023-05-01"))

    def test_sue_with_enough_history(self):
        rows, filed = [], lambda y, m: "%d-%02d-15" % (y + (m + 1) // 12, (m + 1) % 12 + 1)
        ends = [(y, m) for y in range(2019, 2024) for m in (3, 6, 9, 12)]
        for i, (y, m) in enumerate(ends):
            jitter = (0.1, -0.1)[y % 2] if i < len(ends) - 1 else 0.5  # good and bad years; then a big beat
            rows.append([filed(y, m), "ACME", "%d-%02d-%s" % (y, m, "31" if m in (3, 12) else "30"), 1.0 + jitter])
        s = signals.Signals(eps={"rows": rows})
        e = s.eps_surprise("ACME", rows[-1][0])
        self.assertAlmostEqual(e["change"], 0.4)       # 1.5 against 1.1 a year earlier
        self.assertAlmostEqual(e["sue"], 2.0, places=2)  # year-on-year changes usually swing by 0.2

    def test_build_uses_the_ticker_map_and_falls_back_to_basic_eps(self):
        import urllib.error
        calls = []

        def http(url):
            calls.append(url)
            if url == signals.SEC_TICKERS:
                return json.dumps({"0": {"cik_str": 1, "ticker": "ACME"}, "1": {"cik_str": 2, "ticker": "BRK-B"}})
            if "CIK0000000001" in url and "Diluted" in url:
                raise urllib.error.HTTPError(url, 404, "not found", None, None)
            if "CIK0000000001" in url:
                return json.dumps(self.doc())
            return json.dumps({"units": {}})
        doc = signals.build_eps(["ACME", "BRK-B", "NOPE"], "t t@example.com", log=lambda m: None, http=http, pause=0)
        self.assertEqual(len(doc["rows"]), 5)
        self.assertEqual((doc["stats"]["tickers"], doc["stats"]["no_eps"], doc["stats"]["no_cik"]), (1, 1, 1))
        self.assertTrue(any("EarningsPerShareBasic" in c for c in calls))


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
