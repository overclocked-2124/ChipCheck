import json
import math
import struct
import unittest

from activequal.model.canonical import CanonicalError, canonical_json, contract_hash
from activequal.model.examples import oled_example_contract


def from_bits(bits: int) -> float:
    return struct.unpack(">d", bits.to_bytes(8, "big"))[0]


# RFC 8785 Appendix B (IEEE 754 bit pattern -> ECMAScript serialization).
APPENDIX_B = [
    (0x0000000000000000, "0"),
    (0x8000000000000000, "0"),
    (0x0000000000000001, "5e-324"),
    (0x8000000000000001, "-5e-324"),
    (0x7FEFFFFFFFFFFFFF, "1.7976931348623157e+308"),
    (0xFFEFFFFFFFFFFFFF, "-1.7976931348623157e+308"),
    (0x4340000000000000, "9007199254740992"),
    (0xC340000000000000, "-9007199254740992"),
    (0x4430000000000000, "295147905179352830000"),
    (0x44B52D02C7E14AF5, "9.999999999999997e+22"),
    (0x44B52D02C7E14AF6, "1e+23"),
    (0x44B52D02C7E14AF7, "1.0000000000000001e+23"),
    (0x444B1AE4D6E2EF4E, "999999999999999700000"),
    (0x444B1AE4D6E2EF4F, "999999999999999900000"),
    (0x444B1AE4D6E2EF50, "1e+21"),
    (0x3EB0C6F7A0B5ED8C, "9.999999999999997e-7"),
    (0x3EB0C6F7A0B5ED8D, "0.000001"),
    (0x41B3DE4355555553, "333333333.3333332"),
    (0x41B3DE4355555554, "333333333.33333325"),
    (0x41B3DE4355555555, "333333333.3333333"),
    (0x41B3DE4355555556, "333333333.3333334"),
    (0x41B3DE4355555557, "333333333.33333343"),
    (0xBECBF647612F3696, "-0.0000033333333333333333"),
    (0x43143FF3C1CB0959, "1424953923781206.2"),
]


class NumberTests(unittest.TestCase):
    def test_rfc_appendix_b(self):
        for bits, expected in APPENDIX_B:
            with self.subTest(bits=hex(bits)):
                self.assertEqual(canonical_json(from_bits(bits)), expected.encode())

    def test_ecmascript_rules(self):
        cases = {1.0: "1", 0.5: "0.5", 100.0: "100", 1e21: "1e+21", 1e20: "100000000000000000000",
                 1e-6: "0.000001", 1e-7: "1e-7", 1.5e-7: "1.5e-7", 123456789012345680000.0: "123456789012345680000",
                 1.2345678901234567e-7: "1.2345678901234566e-7", -0.0: "0", 0.1 + 0.2: "0.30000000000000004",
                 3.30: "3.3", 1e300: "1e+300", 2 ** 53: "9007199254740992"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(canonical_json(value), expected.encode())

    def test_integers(self):
        self.assertEqual(canonical_json(0), b"0")
        self.assertEqual(canonical_json(-42), b"-42")
        self.assertEqual(canonical_json(2 ** 53), b"9007199254740992")
        self.assertEqual(canonical_json(9007199254740991), b"9007199254740991")
        for bad in (2 ** 53 + 1, -(2 ** 53) - 1, 10 ** 30):
            with self.assertRaises(ValueError):
                canonical_json(bad)

    def test_rejects_non_finite(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                canonical_json(bad)
            with self.assertRaises(ValueError):
                canonical_json({"x": [bad]})

    def test_numbers_match_json_round_trip(self):
        for value in (0.1, 1 / 3, 123.456, 1e-5, 5e-5, 12345.678e10, 2.5e-10, 6.02214076e23, 4.35e15):
            self.assertEqual(float(canonical_json(value)), value)
            self.assertEqual(json.loads(canonical_json(value)), value)


class StructureTests(unittest.TestCase):
    def test_literals_and_booleans(self):
        self.assertEqual(canonical_json([True, False, None, 1]), b"[true,false,null,1]")

    def test_string_escaping(self):
        self.assertEqual(canonical_json('a"b\\c\b\t\n\f\r\x00\x1f\x7f/'),
                         '"a\\"b\\\\c\\b\\t\\n\\f\\r\\u0000\\u001f\x7f/"'.encode())
        self.assertEqual(canonical_json("café € \U0001F600"), '"café € \U0001F600"'.encode())
        with self.assertRaises(ValueError):
            canonical_json("\ud800")

    def test_rfc_sorting_example(self):
        data = {"€": "Euro Sign", "\r": "Carriage Return", "דּ": "Hebrew Letter Dalet With Dagesh",
                "1": "One", "\U0001F600": "Emoji: Grinning Face", "\u0080": "Control",
                "ö": "Latin Small Letter O With Diaeresis"}
        text = canonical_json(data).decode()
        order = [text.index(label) for label in ("Carriage Return", "One", "Control", "Latin Small", "Euro Sign",
                                                 "Emoji", "Hebrew")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(text.startswith('{"\\r":"Carriage Return","1":"One","\u0080":"Control"'))

    def test_utf16_order_not_codepoint_order(self):
        # U+FF5E sorts after U+1F600 in code points but before it in UTF-16 (0xD83D < 0xFF5E).
        text = canonical_json({"～": 1, "\U0001F600": 2}).decode()
        self.assertLess(text.index("\U0001F600"), text.index("～"))

    def test_no_whitespace_and_nesting(self):
        self.assertEqual(canonical_json({"b": [1, {"d": 2, "c": []}], "a": {}}), b'{"a":{},"b":[1,{"c":[],"d":2}]}')
        self.assertEqual(canonical_json((1, 2)), b"[1,2]")

    def test_rfc_example_3_2_2(self):
        raw = "\u20ac$\x0f\nA'B\"\\\\\"/"
        data = {"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
                "string": raw, "literals": [None, True, False]}
        expected = ('{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
                    '"string":"\u20ac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}')
        self.assertEqual(canonical_json(data), expected.encode())

    def test_rejections(self):
        for bad in ({1: "x"}, {"a": object()}, {"a": {1, 2}}, b"bytes", {("a",): 1}):
            with self.assertRaises(ValueError):
                canonical_json(bad)
        deep: object = 1
        for _ in range(500):
            deep = [deep]
        with self.assertRaises(ValueError):
            canonical_json(deep)


class ContractHashTests(unittest.TestCase):
    def test_hash_is_lowercase_sha256_hex(self):
        digest = contract_hash({"a": 1})
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, digest.lower())
        self.assertEqual(digest, "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862")

    def test_key_order_independent(self):
        self.assertEqual(contract_hash({"a": 1, "b": [1, 2], "c": {"x": 1, "y": 2}}),
                         contract_hash({"c": {"y": 2, "x": 1}, "b": [1, 2], "a": 1}))

    def test_list_order_matters(self):
        self.assertNotEqual(contract_hash({"a": [1, 2]}), contract_hash({"a": [2, 1]}))

    def test_float_equivalence(self):
        self.assertEqual(contract_hash({"v": 3.0}), contract_hash({"v": 3}))
        self.assertNotEqual(contract_hash({"v": 0.1 + 0.2}), contract_hash({"v": 0.3}))

    def test_any_field_change_changes_hash(self):
        base = {"a": 1, "b": {"c": [1, "two", None], "d": True}}
        digest = contract_hash(base)
        variants = [{"a": 2, "b": base["b"]}, {"a": 1, "b": {"c": [1, "two", None], "d": False}},
                    {"a": 1, "b": {"c": [1, "twp", None], "d": True}}, {"a": 1, "b": {"c": [1, "two"], "d": True}},
                    {"a": 1, "b": {"c": [1, "two", None], "d": True}, "e": 0},
                    {"a": 1, "b": {"c2": [1, "two", None], "d": True}}]
        for variant in variants:
            self.assertNotEqual(contract_hash(variant), digest)

    def test_oled_contract_stable_and_sensitive(self):
        contract = oled_example_contract()
        digest = contract_hash(contract)
        self.assertEqual(digest, contract_hash(oled_example_contract()))
        self.assertEqual(digest, contract_hash(json.loads(json.dumps(contract))))
        for path in (("controls", "oledRailV", "max"), ("safety", "maxEpisodeS"), ("campaign", "budget")):
            changed = oled_example_contract()
            node = changed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] += 0.01
            self.assertNotEqual(contract_hash(changed), digest, path)
        every_field = oled_example_contract()
        every_field["controls"]["oledRailV"]["slewPerSMax"] = 0.6
        self.assertNotEqual(contract_hash(every_field), digest)


if __name__ == "__main__":
    unittest.main()
