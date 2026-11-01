"""Replace the template hub using a recent, isolated real-execution proof database."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_market.workflow_template_install import replace_templates, verified_recipes

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--verification-db', required=True)
    parser.add_argument('--backup-directory')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        print(replace_templates(args.db, args.verification_db, args.backup_directory or str(Path(args.db).parent / 'security-backups')))
    else:
        print({'verified_endpoints': len(verified_recipes(args.verification_db)), 'action': 'Validation only. Use --apply to replace the hub.'})
