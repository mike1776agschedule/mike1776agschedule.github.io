.PHONY: help decrypt encrypt audit roll-forward dedupe refresh check-pin

PY := python3

help:
	@echo "Florida Ag Dashboard — common targets"
	@echo ""
	@echo "  make decrypt       Decrypt live HTML -> data/records.json"
	@echo "  make encrypt       Encrypt data/records.json -> both HTML files"
	@echo "  make audit         Run 8 QC checks against the live encrypted data"
	@echo "  make roll-forward  Roll past dates to next monthly occurrence"
	@echo "  make dedupe        Remove duplicate (county+org+date) records"
	@echo "  make refresh       Full pipeline: decrypt + roll-forward + dedupe + encrypt + audit"
	@echo ""
	@echo "Then commit with:  python3 scripts/deploy.py 'your message'"
	@echo ""
	@echo "Requires:  export FL_AG_PIN=040476"

check-pin:
	@if [ -z "$$FL_AG_PIN" ]; then \
		echo "ERROR: FL_AG_PIN not set. Run:  export FL_AG_PIN=040476"; \
		exit 1; \
	fi

decrypt: check-pin
	$(PY) scripts/decrypt.py

encrypt: check-pin
	$(PY) scripts/encrypt.py

audit: check-pin
	$(PY) scripts/audit.py

roll-forward:
	$(PY) scripts/roll_forward.py

dedupe:
	$(PY) scripts/dedupe.py

refresh: check-pin decrypt roll-forward dedupe encrypt audit
	@echo ""
	@echo "Refresh complete. To deploy:"
	@echo "  python3 scripts/deploy.py 'Refresh dataset $$(date +%F)'"
