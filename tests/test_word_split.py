import unittest

from word_split import split_stuck_words


class WordSplitTests(unittest.TestCase):
    def test_splits_real_stringtable_values(self):
        expected_pairs = [
            ("AlexPortrait", "Alex Portrait"),
            ("AsaraBurn", "Asara Burn"),
            ("AsaraJugg", "Asara Jugg"),
            ("AsaraRocket", "Asara Rocket"),
            ("AsaraSheild", "Asara Sheild"),
            ("AsaraShotGun", "Asara Shot Gun"),
            ("AsaraSymbol", "Asara Symbol"),
            ("HackClawPortrait", "Hack Claw Portrait"),
            ("KaiPortrait", "Kai Portrait"),
            ("LunaPortrait", "Luna Portrait"),
            ("SmeePortrait", "Smee Portrait"),
            ("TerryPortrait", "Terry Portrait"),
            ("ZoyaPortrait", "Zoya Portrait"),
            ("BPSkyline", "BP Skyline"),
            ("KaiHandGun", "Kai Hand Gun"),
            ("KaiHelmet", "Kai Helmet"),
            ("LunaBow", "Luna Bow"),
            ("SmeeHormone", "Smee Hormone"),
            ("TerryShepherd", "Terry Shepherd"),
            ("TerryUAV", "Terry UAV"),
            ("VirusHealerAngelBP", "Virus Healer Angel BP"),
        ]
        for text, expected in expected_pairs:
            with self.subTest(text=text):
                self.assertEqual(split_stuck_words(text), expected)

    def test_keeps_names_with_digits(self):
        for text in ["AK74", "M4A1", "M4A1S", "MP5K", "Battery9V", "Saiga12K", "556x45"]:
            with self.subTest(text=text):
                self.assertEqual(split_stuck_words(text), text)

    def test_splits_words_before_digits(self):
        self.assertEqual(split_stuck_words("AmmoBox556"), "Ammo Box556")

    def test_leaves_text_with_whitespace_alone(self):
        for text in ["You found AlexPortrait", "already fine", "Bandage ", "Bandage\n"]:
            with self.subTest(text=text):
                self.assertEqual(split_stuck_words(text), text)

    def test_leaves_single_words_alone(self):
        for text in ["Bandage", "A", "AB", "Cfgvehicles", ""]:
            with self.subTest(text=text):
                self.assertEqual(split_stuck_words(text), text)

    def test_splitting_twice_changes_nothing(self):
        for text in ["AlexPortrait", "BPSkyline", "VirusHealerAngelBP", "AsaraShotGun"]:
            once = split_stuck_words(text)
            with self.subTest(text=text):
                self.assertEqual(split_stuck_words(once), once)


if __name__ == "__main__":
    unittest.main()
