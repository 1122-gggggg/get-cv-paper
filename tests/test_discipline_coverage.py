import json
import subprocess
import textwrap
import unittest

import disciplines


def load_frontend_disciplines() -> dict:
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('static/disciplines.js', 'utf8');
        const sandbox = { window: {} };
        sandbox.globalThis = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        console.log(JSON.stringify({
          disciplines: Object.keys(sandbox.window.DISCIPLINES || {}).sort(),
          categoryIds: (sandbox.window.DISCIPLINE_CATEGORIES || [])
            .flatMap(c => c.ids || [])
            .sort(),
        }));
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class DisciplineCoverageTests(unittest.TestCase):
    def test_frontend_disciplines_match_backend(self):
        frontend = load_frontend_disciplines()["disciplines"]
        backend = sorted(disciplines.DISCIPLINES.keys())

        self.assertEqual(frontend, backend)

    def test_picker_categories_cover_every_frontend_discipline_once(self):
        loaded = load_frontend_disciplines()
        frontend = loaded["disciplines"]
        category_ids = loaded["categoryIds"]

        self.assertEqual(category_ids, frontend)
        self.assertEqual(len(category_ids), len(set(category_ids)))


if __name__ == "__main__":
    unittest.main()
