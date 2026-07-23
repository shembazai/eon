#!/usr/bin/env python3
"""
EON_PFA.py

Personal financial assistant with:
- personal profile creation
- multi-income support
- targeted profile editing
- deterministic-first local AI
- mutation firewall
- one-step undo
- CSV change journal
- regression self-test
- profile charts under "View Profile"
"""

import copy
import hashlib
import csv
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:
	import matplotlib.pyplot as plt
except ImportError:
	plt = None

try:
	from llama_cpp import Llama
except ImportError:
	Llama = None


# -------------------- Config --------------------

def _resolve_base_dir() -> Path:
	if os.getenv("K1_EON_DATA_DIR"):
		return Path(os.getenv("K1_EON_DATA_DIR"))
	return Path(os.getenv("EON_PFA_BASE_DIR", Path.home() / "AI"))


def _resolve_models_dir() -> Path:
	if os.getenv("K1_MODELS_DIR"):
		return Path(os.getenv("K1_MODELS_DIR"))
	if os.getenv("K1_EON_DATA_DIR"):
		return Path("/opt/k1/models")
	base = Path(os.getenv("EON_PFA_BASE_DIR", Path.home() / "AI"))
	return base / "models"


BASE_DIR = _resolve_base_dir()
FINANCE_DIR = BASE_DIR if os.getenv("K1_EON_DATA_DIR") else BASE_DIR / "finance"
MODELS_DIR = _resolve_models_dir()
REPORTS_DIR = FINANCE_DIR / "reports"

PROFILE_PATH = FINANCE_DIR / "profile.json"
PROFILE_BACKUP_PATH = FINANCE_DIR / "profile_last_backup.json"
SUMMARY_PATH = FINANCE_DIR / "mastercard_summary.json"
CHANGE_JOURNAL_PATH = FINANCE_DIR / "change_journal.csv"
def _initial_model_path() -> Path:
	"""Resolve startup model path without a brittle hardcoded required filename."""
	from eon.local_models import resolve_model_path

	return resolve_model_path(MODELS_DIR)


MODEL_PATH = _initial_model_path()
PROGRAM_VERSION = "0.1.1"

DEFAULT_CTX = 2048
DEFAULT_THREADS = 6
DEFAULT_GPU_LAYERS = 20

LLM = None

PERSONAL_STANDARD_BILL_PROMPTS = [
	("car loan", "Car loan (monthly)"),
	("phone", "Phone (monthly)"),
	("internet", "Internet (monthly)"),
	("electricity", "Electricity (monthly)"),
	("food", "Food (monthly)"),
	("insurance", "Insurance (monthly)"),
	("transport", "Transport (monthly)"),
	("subscriptions", "Subscriptions (monthly)"),
	("debt", "Debt payment (monthly)"),
	("child support", "Child support (monthly)"),
]

PERSONAL_STANDARD_BILL_ALIASES = {
	"car loan": ["car loan", "car", "loan", "car payment"],
	"phone": ["phone", "cell", "cell phone", "mobile"],
	"internet": ["internet", "wifi", "wi-fi"],
	"electricity": ["electricity", "power", "hydro"],
	"food": ["food", "grocery", "groceries", "épicerie"],
	"insurance": ["insurance", "insurances"],
	"transport": ["transport", "gas", "fuel"],
	"subscriptions": ["subscriptions", "subscription"],
	"debt": ["debt", "debt payment", "debt payment monthly"],
	"child support": ["child support", "pension"],
}

SUPPORTED_MODIFICATION_FIELDS_TEXT = (
	"income, rent, groceries/food, phone, internet, electricity, insurance, "
	"transport, subscriptions, debt, child support, and car loan"
)

GENERIC_AMBIGUOUS_TERMS = {
	"bill",
	"bills",
	"expense",
	"expenses",
	"payment",
	"payments",
	"cost",
	"costs",
	"amount",
	"budget",
	"category",
	"categories",
}

DECISION_FIXED_COSTS_HIGH_PCT = 50.0
DECISION_TOP_EXPENSE_HIGH_PCT = 25.0
DECISION_LOW_MONTHLY_SAVINGS_PCT = 10.0
DECISION_DOMINANCE_RATIO = 1.5


# -------------------- Generic I/O --------------------

def read_json(path):
	if not path.exists():
		return None

	try:
		with open(path, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception as e:
		print(f"❌ Failed to read {path}: {e}")
		return None


def write_json(path, data):
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w", encoding="utf-8") as f:
			json.dump(data, f, indent=4)
		return True
	except Exception as e:
		print(f"❌ Failed to write {path}: {e}")
		return False


def safe_float(value, default=0.0):
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def normalize_text(text):
	return re.sub(r"\s+", " ", str(text).strip().lower())


def normalize_profile_key(text):
	return re.sub(r"\s+", " ", str(text).strip().lower())


def format_money(value):
	return f"${safe_float(value, 0.0):.2f}"


def prune_zero_values(mapping):
	cleaned = {}

	for key, value in (mapping or {}).items():
		amount = round(safe_float(value, 0.0), 2)
		if amount != 0:
			cleaned[str(key)] = amount

	return cleaned


# -------------------- Profile Schema --------------------

def compute_monthly_amount(amount, frequency):
	amount = safe_float(amount, 0.0)
	frequency = normalize_text(frequency)

	if frequency == "weekly":
		return round(amount * 52 / 12, 2)

	if frequency == "bi-weekly" or frequency == "biweekly":
		return round(amount * 26 / 12, 2)

	return round(amount, 2)


def normalize_income_frequency(frequency):
	frequency = normalize_text(frequency)

	if frequency in ("weekly",):
		return "weekly"

	if frequency in ("bi-weekly", "biweekly"):
		return "bi-weekly"

	return "monthly"


def normalize_profile_schema(profile):
	if not isinstance(profile, dict):
		return None

	profile = copy.deepcopy(profile)

	profile_type = normalize_text(profile.get("type", "personal"))
	if not profile_type:
		profile_type = "personal"
	profile["type"] = profile_type

	if "income_streams" not in profile:
		income_data = profile.get("income", {})
		if isinstance(income_data, dict):
			profile["income_streams"] = [{
				"name": "Primary income",
				"amount": round(safe_float(income_data.get("amount", 0.0), 0.0), 2),
				"frequency": normalize_income_frequency(income_data.get("frequency", "monthly")),
			}]
		else:
			profile["income_streams"] = []

	streams = []
	for stream in profile.get("income_streams", []):
		if not isinstance(stream, dict):
			continue

		name = str(stream.get("name", "")).strip() or "Income stream"
		amount = round(safe_float(stream.get("amount", 0.0), 0.0), 2)
		frequency = normalize_income_frequency(stream.get("frequency", "monthly"))

		if amount < 0:
			amount = 0.0

		streams.append({
			"name": name,
			"amount": amount,
			"frequency": frequency,
		})

	profile["income_streams"] = streams
	profile["bills"] = prune_zero_values(profile.get("bills", {}))
	profile["expenses"] = prune_zero_values(profile.get("expenses", {}))

	return profile


def sum_numeric_values(mapping):
	if not isinstance(mapping, dict):
		return 0.0

	total = 0.0
	for value in mapping.values():
		total += safe_float(value, 0.0)

	return round(total, 2)


def compute_monthly_income_from_streams(streams):
	total = 0.0

	for stream in streams or []:
		total += compute_monthly_amount(
			stream.get("amount", 0.0),
			stream.get("frequency", "monthly"),
		)

	return round(total, 2)


def update_profile_estimates(profile):
	profile = normalize_profile_schema(profile)
	if not isinstance(profile, dict):
		return profile

	estimated_monthly_income = compute_monthly_income_from_streams(profile.get("income_streams", []))
	rent = safe_float(profile.get("rent", 0.0), 0.0)
	total_monthly_expenses = round(
		rent
		+ sum_numeric_values(profile.get("bills", {}))
		+ sum_numeric_values(profile.get("expenses", {})),
		2
	)
	estimated_monthly_savings = round(estimated_monthly_income - total_monthly_expenses, 2)

	profile["estimated_monthly_income"] = estimated_monthly_income
	profile["estimated_monthly_expenses"] = total_monthly_expenses
	profile["estimated_monthly_savings"] = estimated_monthly_savings

	return profile


# -------------------- Data Layer --------------------

def load_profile():
	profile = read_json(PROFILE_PATH)
	if profile is None:
		return None
	return normalize_profile_schema(profile)


def save_profile(profile):
	profile = update_profile_estimates(profile)
	return write_json(PROFILE_PATH, profile)


def load_profile_backup():
	backup = read_json(PROFILE_BACKUP_PATH)
	if backup is None:
		return None
	return normalize_profile_schema(backup)


def create_profile_backup(profile):
	profile = update_profile_estimates(profile)
	return write_json(PROFILE_BACKUP_PATH, profile)


def load_mastercard_summary():
	data = read_json(SUMMARY_PATH)

	if data is None:
		return None

	if not isinstance(data, list):
		print("❌ mastercard_summary.json is not a list of transactions.")
		return None

	return data


def get_profile_context():
	profile = load_profile()

	if not profile:
		return None, "❌ No profile found. Create a new profile first with option 1."

	profile_type = normalize_text(profile.get("type", "personal"))
	if profile_type != "personal":
		return (
			None,
			"❌ EON supports personal profiles only in the current release. "
			"Business profiles are out of scope.",
		)

	# In-memory estimates only — do not persist on read (constitution: no undocumented mutation).
	profile = update_profile_estimates(profile)
	return profile, None


def get_credit_context(limit=50):
	transactions = load_mastercard_summary()

	if transactions is None:
		return None, "❌ mastercard_summary.json not found or invalid."

	return transactions[:limit], None


# -------------------- Profile Helpers --------------------

def profile_missing_message():
	return "❌ No profile found. Create a new profile first with option 1."


def build_profile_summary_text(profile):
	profile = update_profile_estimates(profile)
	checking_balance = safe_float(profile.get("checking_balance", 0.0), 0.0)
	savings_total = safe_float(profile.get("savings_total", 0.0), 0.0)
	current_savings = round(checking_balance + savings_total, 2)

	lines = [
		"",
		"📊 Financial Profile Summary",
		f"Type: {profile.get('type', 'personal')}",
		"Income streams:",
	]

	streams = profile.get("income_streams", [])
	if streams:
		for idx, stream in enumerate(streams, 1):
			monthly_value = compute_monthly_amount(
				stream.get("amount", 0.0),
				stream.get("frequency", "monthly"),
			)
			lines.append(
				f" - {idx}. {stream.get('name', 'Income stream')}: "
				f"{format_money(stream.get('amount', 0.0))} ({stream.get('frequency', 'monthly')}) "
				f"≈ {format_money(monthly_value)}/month"
			)
	else:
		lines.append(" - none")

	lines.append(f"Checking account balance: {format_money(checking_balance)}")
	lines.append(f"Total savings / investments: {format_money(savings_total)}")
	lines.append(f"Current savings considered by AI: {format_money(current_savings)}")
	lines.append(f"Rent (monthly): {format_money(profile.get('rent', 0.0))}")

	bills = prune_zero_values(profile.get("bills", {}))
	expenses = prune_zero_values(profile.get("expenses", {}))

	if bills:
		lines.append("Bills (monthly):")
		for key, value in bills.items():
			lines.append(f" - {key}: {format_money(value)}")
	else:
		lines.append("Bills (monthly): none")

	bills_total = sum(bills.values())
	lines.append(f"Total monthly bills: {format_money(bills_total)}")

	if expenses:
		lines.append("Other expenses (monthly):")
		for key, value in expenses.items():
			lines.append(f" - {key}: {format_money(value)}")
	else:
		lines.append("Other expenses (monthly): none")

	expenses_total = sum(expenses.values())
	lines.append(f"Total other expenses: {format_money(expenses_total)}")

	rent_amount = safe_float(profile.get("rent", 0.0), 0.0)
	fixed_costs = round(rent_amount + bills_total, 2)
	total_monthly_outflow = round(fixed_costs + expenses_total, 2)
	lines.append(f"Fixed monthly costs: {format_money(fixed_costs)}")
	lines.append(f"Overall monthly outflow: {format_money(total_monthly_outflow)}")

	monthly_income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	monthly_expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
	monthly_savings = safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0)
	net_cash_flow = round(monthly_income - monthly_expenses, 2)
	lines.append(f"Net monthly cash flow: {format_money(net_cash_flow)}")

	if monthly_savings < 0:
		lines.append("⚠️ Warning: your profile is currently running a monthly deficit. Review income or expenses.")

	if monthly_income > 0:
		lines.append(f"Monthly savings rate: {monthly_savings / monthly_income * 100:.1f}%")
		lines.append(f"Expenses as % of income: {monthly_expenses / monthly_income * 100:.1f}%")

	lines.append(f"Estimated monthly income: {format_money(monthly_income)}")
	lines.append(f"Estimated monthly expenses: {format_money(monthly_expenses)}")
	lines.append(f"Estimated monthly savings: {format_money(monthly_savings)}")
	lines.append(f"Profile file: {PROFILE_PATH}")

	return "\n".join(lines)

def split_standard_and_custom_bills(profile):
	bills = profile.get("bills", {})
	if not isinstance(bills, dict):
		bills = {}

	standard = {key: 0.0 for key, _label in PERSONAL_STANDARD_BILL_PROMPTS}
	custom = {}

	for key, value in bills.items():
		key_n = normalize_profile_key(key)
		matched = None

		for canonical, aliases in PERSONAL_STANDARD_BILL_ALIASES.items():
			for alias in aliases:
				if key_n == normalize_profile_key(alias):
					matched = canonical
					break
			if matched is not None:
				break

		if matched is not None:
			standard[matched] = round(safe_float(value, 0.0), 2)
		else:
			custom[str(key)] = round(safe_float(value, 0.0), 2)

	return standard, prune_zero_values(custom)


# -------------------- Prompt Helpers --------------------

def prompt_text_input(label, allow_empty=False, default=None):
	while True:
		suffix = f" [{default}]" if default is not None else ""
		raw = input(f"{label}{suffix}: ").strip()

		if not raw and default is not None:
			return str(default)

		if raw or allow_empty:
			return raw

		print("❌ This field cannot be empty.")


def prompt_choice_input(label, choices_map, default_key=None):
	valid_keys = list(choices_map.keys())
	display = ", ".join([f"{key}={choices_map[key]}" for key in valid_keys])

	while True:
		prompt = f"{label} ({display})"
		if default_key is not None:
			prompt += f" [{default_key}]"

		raw = input(prompt + ": ").strip().lower()

		if not raw and default_key is not None:
			raw = str(default_key).lower()

		if raw in choices_map:
			return choices_map[raw]

		print("❌ Invalid choice.")


def prompt_money_input(label, allow_zero=True, default=None):
	while True:
		suffix = ""
		if default is not None:
			suffix = f" [{default}]"

		raw = input(f"{label}{suffix}: ").strip()

		if not raw and default is not None:
			return round(safe_float(default, 0.0), 2)

		try:
			value = float(raw.replace(",", "").replace("$", ""))
		except ValueError:
			print("❌ Invalid amount. Enter a numeric value.")
			continue

		if value < 0:
			print("❌ Negative amounts are not allowed.")
			continue

		if not allow_zero and value == 0:
			print("❌ Value must be greater than zero.")
			continue

		return round(value, 2)


def prompt_yes_no(label, default="n"):
	default = normalize_text(default)
	suffix = " [y/N]" if default == "n" else " [Y/n]"

	while True:
		raw = normalize_text(input(f"{label}{suffix}: "))

		if not raw:
			raw = default

		if raw in ("y", "yes"):
			return True

		if raw in ("n", "no"):
			return False

		print("❌ Enter y or n.")


def choose_from_mapping(title, mapping):
	keys = list(mapping.keys())

	if not keys:
		print(f"⚠️ No {title.lower()} found.")
		return None

	print(f"\n{title}:")
	for idx, key in enumerate(keys, 1):
		print(f"{idx}. {key} ({format_money(mapping[key])})")
	print("0. Cancel")

	while True:
		raw = input("Select an option: ").strip()
		if raw == "0":
			return None
		if raw.isdigit():
			n = int(raw)
			if 1 <= n <= len(keys):
				return keys[n - 1]
		print("❌ Invalid option.")


# -------------------- Income Stream Editing --------------------

def collect_income_streams(existing_streams=None, require_one=True):
	streams = copy.deepcopy(existing_streams or [])

	if streams:
		print("\nCurrent income streams:")
		for idx, stream in enumerate(streams, 1):
			print(
				f" - {idx}. {stream.get('name', 'Income stream')}: "
				f"{format_money(stream.get('amount', 0.0))} ({stream.get('frequency', 'monthly')})"
			)

	while True:
		if streams and not prompt_yes_no("Add another income stream?", default="n"):
			break

		if not streams and require_one:
			print("\nAdd at least one income stream.")
		elif not prompt_yes_no("Add an income stream?", default="n"):
			break

		name = prompt_text_input("Income stream name", allow_empty=False)
		frequency = prompt_choice_input(
			"Income frequency",
			{
				"1": "monthly",
				"2": "weekly",
				"3": "bi-weekly",
				"monthly": "monthly",
				"weekly": "weekly",
				"bi-weekly": "bi-weekly",
				"biweekly": "bi-weekly",
			},
			default_key="1",
		)
		amount = prompt_money_input("Income amount", allow_zero=False)

		streams.append({
			"name": name,
			"amount": amount,
			"frequency": frequency,
		})

		if not require_one and not prompt_yes_no("Add another income stream?", default="n"):
			break

	return streams


def edit_income_streams(profile):
	updated = copy.deepcopy(profile)

	while True:
		updated = update_profile_estimates(updated)
		streams = updated.get("income_streams", [])

		print("\n=== Edit Income Streams ===")
		if streams:
			for idx, stream in enumerate(streams, 1):
				monthly_value = compute_monthly_amount(stream.get("amount", 0.0), stream.get("frequency", "monthly"))
				print(
					f"{idx}. {stream.get('name', 'Income stream')} - "
					f"{format_money(stream.get('amount', 0.0))} ({stream.get('frequency', 'monthly')}) "
					f"≈ {format_money(monthly_value)}/month"
				)
		else:
			print("No income streams found.")

		print("a. Add income stream")
		print("0. Back")

		raw = input("Select an option: ").strip().lower()

		if raw == "0":
			return updated

		if raw == "a":
			name = prompt_text_input("Income stream name", allow_empty=False)
			frequency = prompt_choice_input(
				"Income frequency",
				{
					"1": "monthly",
					"2": "weekly",
					"3": "bi-weekly",
					"monthly": "monthly",
					"weekly": "weekly",
					"bi-weekly": "bi-weekly",
					"biweekly": "bi-weekly",
				},
				default_key="1",
			)
			amount = prompt_money_input("Income amount", allow_zero=False)
			updated.setdefault("income_streams", []).append({
				"name": name,
				"amount": amount,
				"frequency": frequency,
			})
			print(build_profile_summary_text(updated))
			print("✅ Income stream added.")
			continue

		if not raw.isdigit():
			print("❌ Invalid option.")
			continue

		idx = int(raw)
		if idx < 1 or idx > len(streams):
			print("❌ Invalid option.")
			continue

		stream = streams[idx - 1]

		while True:
			print(f"\nEditing income stream: {stream.get('name', 'Income stream')}")
			print("1. Change name")
			print("2. Change amount")
			print("3. Change frequency")
			print("4. Remove")
			print("0. Back")

			choice = input("Select an option: ").strip()

			if choice == "0":
				break

			if choice == "1":
				stream["name"] = prompt_text_input(
					"Income stream name",
					allow_empty=False,
					default=stream.get("name", "Income stream"),
				)
				print(build_profile_summary_text(updated))
				print("✅ Income stream updated.")

			elif choice == "2":
				stream["amount"] = prompt_money_input(
					"Income amount",
					allow_zero=False,
					default=f"{safe_float(stream.get('amount', 0.0), 0.0):.2f}",
				)
				print(build_profile_summary_text(updated))
				print("✅ Income stream updated.")

			elif choice == "3":
				stream["frequency"] = prompt_choice_input(
					"Income frequency",
					{
						"1": "monthly",
						"2": "weekly",
						"3": "bi-weekly",
						"monthly": "monthly",
						"weekly": "weekly",
						"bi-weekly": "bi-weekly",
						"biweekly": "bi-weekly",
					},
					default_key=str(stream.get("frequency", "monthly")).lower(),
				)
				print(build_profile_summary_text(updated))
				print("✅ Income stream updated.")

			elif choice == "4":
				if len(streams) == 1:
					print("❌ You must keep at least one income stream.")
					continue

				if not prompt_yes_no(f"Remove income stream '{stream.get('name', 'Income stream')}'?", default="n"):
					print("⚠️ Removal cancelled.")
					continue

				streams.pop(idx - 1)
				print(build_profile_summary_text(updated))
				print("✅ Income stream removed.")
				break

			else:
				print("❌ Invalid option.")

		updated["income_streams"] = streams


# -------------------- Profile Creation / Editing --------------------

def create_new_profile():
	FINANCE_DIR.mkdir(parents=True, exist_ok=True)

	existing_profile = load_profile()
	if existing_profile and not prompt_yes_no("A profile already exists. Overwrite it?", default="n"):
		print("⚠️ Profile creation cancelled.")
		return

	print("\n=== Create New Profile ===")
	print("Enter your core personal financial information. Recurring amounts below are monthly by default.")

	income_streams = collect_income_streams(require_one=True)
	checking_balance = prompt_money_input("Checking account balance", allow_zero=True, default="0")
	savings_total = prompt_money_input("Total savings / investments (TFSA, RRSP, etc.)", allow_zero=True, default="0")
	rent = prompt_money_input("Rent (monthly)", allow_zero=True, default="0")

	bills = {}
	for key, label in PERSONAL_STANDARD_BILL_PROMPTS:
		bills[key] = prompt_money_input(label, allow_zero=True, default="0")

	custom_bills = {}
	while prompt_yes_no("Add another custom bill?", default="n"):
		name = prompt_text_input("Custom bill name", allow_empty=False)
		amount = prompt_money_input("Amount (monthly)", allow_zero=True, default="0")
		if amount == 0:
			print("⚠️ Zero amount skipped.")
			continue
		custom_bills[name] = amount

	expenses = {}
	while prompt_yes_no("Add another custom extra expense?", default="n"):
		name = prompt_text_input("Custom extra expense name", allow_empty=False)
		amount = prompt_money_input("Amount (monthly)", allow_zero=True, default="0")
		if amount == 0:
			print("⚠️ Zero amount skipped.")
			continue
		expenses[name] = amount

	profile = {
		"type": "personal",
		"income_streams": income_streams,
		"checking_balance": checking_balance,
		"savings_total": savings_total,
		"current_savings": round(checking_balance + savings_total, 2),
		"rent": rent,
		"bills": prune_zero_values({**bills, **custom_bills}),
		"expenses": prune_zero_values(expenses),
	}

	profile = update_profile_estimates(profile)

	if not save_profile(profile):
		print("❌ Failed to save profile.")
		return

	create_profile_backup(profile)

	print(build_profile_summary_text(profile))
	print("✅ Profile creation complete.")

def edit_profile():
	profile = load_profile()
	if not profile:
		print(profile_missing_message())
		return

	if normalize_text(profile.get("type", "personal")) != "personal":
		print("❌ This program now supports personal profiles only. Create a new personal profile with option 1.")
		return

	profile = update_profile_estimates(profile)

	def save_updated_profile(original_profile, updated_profile):
		updated_profile["current_savings"] = round(
			safe_float(updated_profile.get("checking_balance", 0.0), 0.0)
			+ safe_float(updated_profile.get("savings_total", 0.0), 0.0),
			2,
		)
		updated_profile = update_profile_estimates(updated_profile)

		if updated_profile == original_profile:
			print("No effective change was applied. The requested values already match the current profile.")
			return False

		if not create_profile_backup(original_profile):
			print("❌ Existing profile could not be backed up.")
			return False

		if not save_profile(updated_profile):
			print("❌ Failed to save updated profile.")
			return False

		print(build_profile_summary_text(updated_profile))
		print("✅ Profile update complete.")
		return True

	while True:
		profile = load_profile()
		if not profile:
			print(profile_missing_message())
			return

		profile = update_profile_estimates(profile)
		standard_bills, custom_bills = split_standard_and_custom_bills(profile)
		extra_expenses = prune_zero_values(profile.get("expenses", {}))

		print("\n=== Edit Profile (Personal) ===")
		print("1. Edit income streams")
		print(
			f"2. Edit current savings balances "
			f"(checking: {format_money(profile.get('checking_balance', 0.0))}, "
			f"savings: {format_money(profile.get('savings_total', 0.0))})"
		)
		print(f"3. Edit rent (monthly) (current: {format_money(profile.get('rent', 0.0))})")
		print("4. Edit standard monthly bills")
		print("5. Edit custom monthly bills")
		print("6. Edit extra monthly expenses")
		print("0. Back")

		choice = input("Select an option: ").strip()

		if choice == "0":
			return

		elif choice == "1":
			updated = edit_income_streams(copy.deepcopy(profile))
			save_updated_profile(profile, updated)

		elif choice == "2":
			updated = copy.deepcopy(profile)
			updated["checking_balance"] = prompt_money_input(
				"Checking account balance",
				allow_zero=True,
				default=f"{safe_float(profile.get('checking_balance', 0.0), 0.0):.2f}",
			)
			updated["savings_total"] = prompt_money_input(
				"Total savings / investments (TFSA, RRSP, etc.)",
				allow_zero=True,
				default=f"{safe_float(profile.get('savings_total', 0.0), 0.0):.2f}",
			)
			save_updated_profile(profile, updated)

		elif choice == "3":
			new_rent = prompt_money_input(
				"Rent (monthly)",
				allow_zero=True,
				default=f"{safe_float(profile.get('rent', 0.0), 0.0):.2f}",
			)
			updated = copy.deepcopy(profile)
			updated["rent"] = new_rent
			save_updated_profile(profile, updated)

		elif choice == "4":
			current_mapping = {label: standard_bills.get(key, 0.0) for key, label in PERSONAL_STANDARD_BILL_PROMPTS}
			selected_label = choose_from_mapping("Standard monthly bills", current_mapping)
			if selected_label is None:
				continue

			canonical_key = None
			for key, label in PERSONAL_STANDARD_BILL_PROMPTS:
				if label == selected_label:
					canonical_key = key
					break

			if canonical_key is None:
				print("❌ Could not resolve bill selection.")
				continue

			current_amount = standard_bills.get(canonical_key, 0.0)

			print(f"\nEditing standard bill: {selected_label}")
			print("1. Change amount")
			print("2. Clear / remove")
			print("0. Back")

			action = input("Select an option: ").strip()

			if action == "0":
				continue

			updated = copy.deepcopy(profile)
			updated.setdefault("bills", {})

			if action == "1":
				new_amount = prompt_money_input(
					f"{selected_label}",
					allow_zero=True,
					default=f"{safe_float(current_amount, 0.0):.2f}",
				)
				updated["bills"][canonical_key] = new_amount
				updated["bills"] = prune_zero_values(updated["bills"])
				save_updated_profile(profile, updated)

			elif action == "2":
				updated["bills"].pop(canonical_key, None)
				save_updated_profile(profile, updated)

			else:
				print("❌ Invalid option.")

		elif choice == "5":
			selected = choose_from_mapping("Custom monthly bills", custom_bills)
			if selected is None:
				if prompt_yes_no("Add a new custom monthly bill?", default="n"):
					name = prompt_text_input("Custom bill name", allow_empty=False)
					amount = prompt_money_input("Amount (monthly)", allow_zero=True, default="0")
					if amount == 0:
						print("⚠️ Zero amount skipped.")
						continue
					updated = copy.deepcopy(profile)
					updated.setdefault("bills", {})
					updated["bills"][name] = amount
					save_updated_profile(profile, updated)
				continue

			print(f"\nEditing custom monthly bill: {selected}")
			print("1. Change amount")
			print("2. Remove")
			print("0. Back")

			action = input("Select an option: ").strip()

			if action == "0":
				continue

			updated = copy.deepcopy(profile)
			updated.setdefault("bills", {})

			if action == "1":
				new_amount = prompt_money_input(
					f"{selected}",
					allow_zero=True,
					default=f"{safe_float(custom_bills.get(selected, 0.0), 0.0):.2f}",
				)
				updated["bills"][selected] = new_amount
				updated["bills"] = prune_zero_values(updated["bills"])
				save_updated_profile(profile, updated)

			elif action == "2":
				updated["bills"].pop(selected, None)
				save_updated_profile(profile, updated)

			else:
				print("❌ Invalid option.")

		elif choice == "6":
			selected = choose_from_mapping("Extra monthly expenses", extra_expenses)
			if selected is None:
				if prompt_yes_no("Add a new extra monthly expense?", default="n"):
					name = prompt_text_input("Extra expense name", allow_empty=False)
					amount = prompt_money_input("Amount (monthly)", allow_zero=True, default="0")
					if amount == 0:
						print("⚠️ Zero amount skipped.")
						continue
					updated = copy.deepcopy(profile)
					updated.setdefault("expenses", {})
					updated["expenses"][name] = amount
					save_updated_profile(profile, updated)
				continue

			print(f"\nEditing extra monthly expense: {selected}")
			print("1. Change amount")
			print("2. Remove")
			print("0. Back")

			action = input("Select an option: ").strip()

			if action == "0":
				continue

			updated = copy.deepcopy(profile)
			updated.setdefault("expenses", {})

			if action == "1":
				new_amount = prompt_money_input(
					f"{selected}",
					allow_zero=True,
					default=f"{safe_float(extra_expenses.get(selected, 0.0), 0.0):.2f}",
				)
				updated["expenses"][selected] = new_amount
				updated["expenses"] = prune_zero_values(updated["expenses"])
				save_updated_profile(profile, updated)

			elif action == "2":
				updated["expenses"].pop(selected, None)
				save_updated_profile(profile, updated)

			else:
				print("❌ Invalid option.")

		else:
			print("❌ Invalid option.")

def build_totals_snapshot(profile):
	snapshot = update_profile_estimates(copy.deepcopy(profile))
	return {
		"monthly_income": safe_float(snapshot.get("estimated_monthly_income", 0.0), 0.0),
		"monthly_expenses": safe_float(snapshot.get("estimated_monthly_expenses", 0.0), 0.0),
		"monthly_savings": safe_float(snapshot.get("estimated_monthly_savings", 0.0), 0.0),
	}


def append_change_journal(command, changed_fields, before_profile, after_profile):
	CHANGE_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

	before_totals = build_totals_snapshot(before_profile)
	after_totals = build_totals_snapshot(after_profile)

	row = {
		"timestamp": datetime.now().isoformat(timespec="seconds"),
		"original_command": str(command).strip(),
		"fields_changed": "|".join(changed_fields),
		"before_monthly_income": f"{before_totals['monthly_income']:.2f}",
		"before_monthly_expenses": f"{before_totals['monthly_expenses']:.2f}",
		"before_monthly_savings": f"{before_totals['monthly_savings']:.2f}",
		"after_monthly_income": f"{after_totals['monthly_income']:.2f}",
		"after_monthly_expenses": f"{after_totals['monthly_expenses']:.2f}",
		"after_monthly_savings": f"{after_totals['monthly_savings']:.2f}",
	}

	fieldnames = [
		"timestamp",
		"original_command",
		"fields_changed",
		"before_monthly_income",
		"before_monthly_expenses",
		"before_monthly_savings",
		"after_monthly_income",
		"after_monthly_expenses",
		"after_monthly_savings",
	]

	try:
		write_header = not CHANGE_JOURNAL_PATH.exists() or CHANGE_JOURNAL_PATH.stat().st_size == 0
		with open(CHANGE_JOURNAL_PATH, "a", encoding="utf-8", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			if write_header:
				writer.writeheader()
			writer.writerow(row)
		return True, None
	except Exception as e:
		return False, f"⚠️ Changes were saved, but the change journal could not be updated: {e}"


def count_change_journal_entries():
	if not CHANGE_JOURNAL_PATH.exists():
		return 0

	try:
		lines = [line for line in CHANGE_JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
	except Exception:
		return 0

	if not lines:
		return 0

	return max(len(lines) - 1, 0)


# -------------------- Analysis Layer --------------------

def build_pie_chart(category_totals, title, output_path):
	if plt is None:
		return None

	filtered = {}

	for label, value in category_totals.items():
		amount = abs(safe_float(value, 0.0))
		if amount > 0:
			filtered[str(label)] = amount

	if not filtered:
		return None

	output_path.parent.mkdir(parents=True, exist_ok=True)

	labels = list(filtered.keys())
	values = list(filtered.values())

	plt.figure(figsize=(8, 8))
	plt.pie(
		values,
		labels=labels,
		autopct=lambda pct: f"{pct:.1f}%" if pct > 0 else "",
		startangle=90,
		counterclock=False,
	)
	plt.title(title)
	plt.tight_layout()
	plt.savefig(output_path)
	plt.close()

	return output_path


def build_profile_budget_categories(profile):
	profile = update_profile_estimates(profile)
	category_totals = {"rent": safe_float(profile.get("rent", 0.0), 0.0)}

	for key, value in profile.get("bills", {}).items():
		category_totals[str(key)] = round(safe_float(value, 0.0), 2)

	for key, value in profile.get("expenses", {}).items():
		category_totals[str(key)] = round(safe_float(value, 0.0), 2)

	return category_totals


def build_credit_categories(transactions):
	category_totals = {}

	for tx in transactions:
		category = tx.get("category", "other")
		amount = abs(safe_float(tx.get("amount", 0.0), 0.0))
		category_totals[str(category)] = round(category_totals.get(str(category), 0.0) + amount, 2)

	return category_totals


def parse_money_value(text):
	match = re.search(r"\$?\s*(-?[0-9]+(?:[.,][0-9]{1,2})?)", text)
	if not match:
		return None
	return safe_float(match.group(1).replace(",", ""), None)


def parse_target_amount(prompt):
	return parse_money_value(prompt)


def extract_current_savings(profile, prompt):
	prompt_l = normalize_text(prompt)

	explicit_patterns = [
		r"(?:current savings|current balance|savings balance)\s*(?:is|=|:)?\s*\$?\s*([0-9]+(?:[.,][0-9]{1,2})?)",
		r"(?:my current savings|my savings balance|my current balance)\s*(?:is|=|:)?\s*\$?\s*([0-9]+(?:[.,][0-9]{1,2})?)",
		r"(?:i currently have saved|i have saved|i already have saved)\s*\$?\s*([0-9]+(?:[.,][0-9]{1,2})?)",
	]

	for pattern in explicit_patterns:
		match = re.search(pattern, prompt_l)
		if match:
			return round(safe_float(match.group(1).replace(",", ""), 0.0), 2)

	if "checking_balance" in profile or "savings_total" in profile:
		return round(
			safe_float(profile.get("checking_balance", 0.0), 0.0)
			+ safe_float(profile.get("savings_total", 0.0), 0.0),
			2,
		)

	for key in ["current_savings", "savings", "savings_balance", "balance"]:
		if key in profile:
			return round(safe_float(profile.get(key), 0.0), 2)

	return 0.0

def parse_time_horizon_months(prompt):
	prompt_l = normalize_text(prompt)

	year_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*years?", prompt_l)
	if year_match:
		years = safe_float(year_match.group(1).replace(",", ""), None)
		if years is not None:
			return years * 12

	month_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*months?", prompt_l)
	if month_match:
		months = safe_float(month_match.group(1).replace(",", ""), None)
		if months is not None:
			return months

	return None


def detect_category_from_prompt(prompt):
	prompt_l = normalize_text(prompt)

	category_aliases = {
		"food": ["food", "grocery", "groceries", "épicerie"],
		"transport": ["transport", "gas", "fuel"],
		"rent": ["rent"],
		"child support": ["child support", "pension"],
		"phone": ["phone", "cell", "cell phone", "mobile"],
		"internet": ["internet", "wifi", "wi-fi"],
		"electricity": ["electricity", "power", "hydro"],
		"insurance": ["insurance"],
		"subscriptions": ["subscriptions", "subscription"],
		"debt": ["debt", "debt payment"],
		"car loan": ["car loan", "car payment", "car"],
	}

	for canonical, aliases in category_aliases.items():
		for alias in aliases:
			if re.search(rf"\b{re.escape(alias)}\b", prompt_l):
				return canonical

	return None

def get_profile_category_amount(profile, category):
	bills = profile.get("bills", {})
	expenses = profile.get("expenses", {})

	if category == "rent":
		return safe_float(profile.get("rent", 0.0), 0.0)

	return round(
		safe_float(bills.get(category, 0.0), 0.0)
		+ safe_float(expenses.get(category, 0.0), 0.0),
		2
	)


def get_aggregate_amount(profile, prompt):
	prompt_l = normalize_text(prompt)

	rent = safe_float(profile.get("rent", 0.0), 0.0)
	bills_total = sum_numeric_values(profile.get("bills", {}))
	extras_total = sum_numeric_values(profile.get("expenses", {}))
	total_expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
	non_rent_expenses = round(total_expenses - rent, 2)

	if "total bills" in prompt_l or "all bills" in prompt_l or "bills total" in prompt_l or "on bills" in prompt_l:
		return "total bills", bills_total

	if "non-rent expenses" in prompt_l or "non rent expenses" in prompt_l:
		return "non-rent expenses", non_rent_expenses

	if "total expenses" in prompt_l or "all expenses" in prompt_l:
		return "total expenses", total_expenses

	if "extra expenses" in prompt_l or "other expenses" in prompt_l:
		return "other expenses", extras_total

	return None, None


def build_expense_ranking(profile):
	ranking = []

	ranking.append(("rent", round(safe_float(profile.get("rent", 0.0), 0.0), 2)))

	for label, value in profile.get("bills", {}).items():
		value = safe_float(value, 0.0)
		if value > 0:
			ranking.append((str(label), round(value, 2)))

	for label, value in profile.get("expenses", {}).items():
		value = safe_float(value, 0.0)
		if value > 0:
			ranking.append((str(label), round(value, 2)))

	final_ranking = sorted(ranking, key=lambda x: x[1], reverse=True)
	return final_ranking


# -------------------- Forecasting Core --------------------

def extract_starting_cash(profile, prompt=""):
	return round(extract_current_savings(profile, prompt), 2)


def normalize_forecast_request(
	mode,
	horizon_months=12,
	starting_cash_override=None,
	monthly_income_override=None,
	monthly_expenses_override=None,
	monthly_savings_override=None,
	goal_amount=None,
	scenario_delta=None,
):
	mode = normalize_text(mode)
	allowed_modes = {
		"baseline_projection",
		"savings_curve",
		"expense_projection",
		"goal_eta",
		"scenario_projection",
	}
	if mode not in allowed_modes:
		raise ValueError(f"Unsupported forecast mode: {mode}")

	try:
		horizon_value = float(horizon_months)
	except (TypeError, ValueError) as exc:
		raise ValueError("horizon_months must be numeric.") from exc

	if horizon_value <= 0:
		raise ValueError("horizon_months must be greater than zero.")

	horizon_months_int = max(1, min(int(math.ceil(horizon_value)), 60))

	request = {
		"mode": mode,
		"horizon_months": horizon_months_int,
		"starting_cash_override": None if starting_cash_override is None else round(safe_float(starting_cash_override, 0.0), 2),
		"monthly_income_override": None if monthly_income_override is None else round(safe_float(monthly_income_override, 0.0), 2),
		"monthly_expenses_override": None if monthly_expenses_override is None else round(safe_float(monthly_expenses_override, 0.0), 2),
		"monthly_savings_override": None if monthly_savings_override is None else round(safe_float(monthly_savings_override, 0.0), 2),
		"goal_amount": None if goal_amount is None else round(safe_float(goal_amount, 0.0), 2),
		"scenario_delta": {},
	}

	if scenario_delta is not None:
		if not isinstance(scenario_delta, dict):
			raise ValueError("scenario_delta must be a dict.")

		normalized_delta = {}
		for key, value in scenario_delta.items():
			key_n = normalize_text(key)
			if not key_n:
				continue
			normalized_delta[key_n] = round(safe_float(value, 0.0), 2)
		request["scenario_delta"] = normalized_delta

	if mode == "goal_eta" and request["goal_amount"] is None:
		raise ValueError("goal_amount is required for goal_eta forecasts.")

	return request


def build_monthly_projection(starting_cash, monthly_income, monthly_expenses, horizon_months):
	starting_cash = round(safe_float(starting_cash, 0.0), 2)
	monthly_income = round(safe_float(monthly_income, 0.0), 2)
	monthly_expenses = round(safe_float(monthly_expenses, 0.0), 2)
	monthly_savings = round(monthly_income - monthly_expenses, 2)
	horizon_months = int(horizon_months)

	projection_points = []
	projected_cash = starting_cash

	for month_index in range(1, horizon_months + 1):
		projected_cash = round(projected_cash + monthly_savings, 2)
		projection_points.append({
			"month_index": month_index,
			"projected_cash": projected_cash,
			"projected_income": monthly_income,
			"projected_expenses": monthly_expenses,
			"projected_savings": monthly_savings,
		})

	return projection_points


def build_forecast_signature(payload):
	canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def forecast_baseline(profile, horizon_months=12, overrides=None):
	profile = update_profile_estimates(copy.deepcopy(profile))
	overrides = overrides or {}
	request = normalize_forecast_request(
		mode="baseline_projection",
		horizon_months=horizon_months,
		starting_cash_override=overrides.get("starting_cash_override"),
		monthly_income_override=overrides.get("monthly_income_override"),
		monthly_expenses_override=overrides.get("monthly_expenses_override"),
		monthly_savings_override=overrides.get("monthly_savings_override"),
	)

	starting_cash = request["starting_cash_override"]
	if starting_cash is None:
		starting_cash = extract_starting_cash(profile)

	monthly_income = request["monthly_income_override"]
	if monthly_income is None:
		monthly_income = round(safe_float(profile.get("estimated_monthly_income", 0.0), 0.0), 2)

	monthly_expenses = request["monthly_expenses_override"]
	if monthly_expenses is None:
		monthly_expenses = round(safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0), 2)

	monthly_savings_override = request["monthly_savings_override"]
	if monthly_savings_override is not None:
		monthly_expenses = round(monthly_income - monthly_savings_override, 2)

	monthly_savings = round(monthly_income - monthly_expenses, 2)
	projection_points = build_monthly_projection(
		starting_cash,
		monthly_income,
		monthly_expenses,
		request["horizon_months"],
	)
	ending_cash = round(projection_points[-1]["projected_cash"] if projection_points else starting_cash, 2)

	result = {
		"mode": request["mode"],
		"horizon_months": request["horizon_months"],
		"starting_cash": round(starting_cash, 2),
		"monthly_income": round(monthly_income, 2),
		"monthly_expenses": round(monthly_expenses, 2),
		"monthly_savings": round(monthly_savings, 2),
		"projection_points": projection_points,
		"ending_cash": ending_cash,
		"goal_reached": False,
		"goal_month": None,
		"assumptions": [
			"monthly income held constant",
			"monthly expenses held constant",
			"no stochastic variation",
			"starting cash derived from profile unless overridden",
		],
		"warnings": [],
	}
	result["deterministic_signature"] = build_forecast_signature(result)
	return result


def forecast_goal_eta(profile, goal_amount, overrides=None):
	profile = update_profile_estimates(copy.deepcopy(profile))
	request = normalize_forecast_request(
		mode="goal_eta",
		horizon_months=60,
		goal_amount=goal_amount,
		starting_cash_override=(overrides or {}).get("starting_cash_override"),
		monthly_income_override=(overrides or {}).get("monthly_income_override"),
		monthly_expenses_override=(overrides or {}).get("monthly_expenses_override"),
		monthly_savings_override=(overrides or {}).get("monthly_savings_override"),
	)
	baseline = forecast_baseline(profile, horizon_months=request["horizon_months"], overrides=request)
	starting_cash = baseline["starting_cash"]
	monthly_savings = baseline["monthly_savings"]
	goal_amount = request["goal_amount"]
	warnings = list(baseline["warnings"])

	if goal_amount <= starting_cash:
		exact_months = 0.0
		goal_month = 0
		goal_reached = True
		months_to_goal = 0
		ending_cash = starting_cash
		projection_points = []
	elif monthly_savings <= 0:
		exact_months = None
		goal_month = None
		goal_reached = False
		months_to_goal = None
		ending_cash = baseline["ending_cash"]
		projection_points = baseline["projection_points"]
		warnings.append("goal is unreachable under current monthly savings")
	else:
		remaining = round(goal_amount - starting_cash, 2)
		exact_months = remaining / monthly_savings
		months_to_goal = int(math.ceil(exact_months))
		goal_month = months_to_goal
		goal_reached = months_to_goal <= baseline["horizon_months"]
		if goal_reached:
			projection_points = build_monthly_projection(
				starting_cash,
				baseline["monthly_income"],
				baseline["monthly_expenses"],
				months_to_goal,
			)
			ending_cash = round(projection_points[-1]["projected_cash"] if projection_points else starting_cash, 2)
		else:
			projection_points = baseline["projection_points"]
			ending_cash = baseline["ending_cash"]
			warnings.append("goal extends beyond current forecast horizon")

	result = {
		"mode": request["mode"],
		"horizon_months": baseline["horizon_months"],
		"starting_cash": starting_cash,
		"monthly_income": baseline["monthly_income"],
		"monthly_expenses": baseline["monthly_expenses"],
		"monthly_savings": monthly_savings,
		"goal_amount": goal_amount,
		"goal_reached": goal_reached,
		"goal_month": goal_month,
		"exact_months_to_goal": None if exact_months is None else round(exact_months, 2),
		"projection_points": projection_points,
		"ending_cash": ending_cash,
		"assumptions": list(baseline["assumptions"]),
		"warnings": warnings,
	}
	result["deterministic_signature"] = build_forecast_signature(result)
	return result


def forecast_scenario(profile, horizon_months=12, scenario_delta=None, overrides=None):
	profile = update_profile_estimates(copy.deepcopy(profile))
	overrides = overrides or {}
	request = normalize_forecast_request(
		mode="scenario_projection",
		horizon_months=horizon_months,
		starting_cash_override=overrides.get("starting_cash_override"),
		monthly_income_override=overrides.get("monthly_income_override"),
		monthly_expenses_override=overrides.get("monthly_expenses_override"),
		monthly_savings_override=overrides.get("monthly_savings_override"),
		scenario_delta=scenario_delta or {},
	)
	baseline = forecast_baseline(profile, horizon_months=request["horizon_months"], overrides=request)
	monthly_income = baseline["monthly_income"]
	monthly_expenses = baseline["monthly_expenses"]
	warnings = []

	for key, delta in request["scenario_delta"].items():
		if key == "income":
			monthly_income = round(monthly_income + delta, 2)
		elif key in {"expenses", "total expenses", "total_expenses"}:
			monthly_expenses = round(monthly_expenses + delta, 2)
		elif key == "rent":
			monthly_expenses = round(monthly_expenses + delta, 2)
		else:
			warnings.append(f"unsupported scenario field ignored: {key}")

	monthly_savings = round(monthly_income - monthly_expenses, 2)
	projection_points = build_monthly_projection(
		baseline["starting_cash"],
		monthly_income,
		monthly_expenses,
		request["horizon_months"],
	)
	ending_cash = round(projection_points[-1]["projected_cash"] if projection_points else baseline["starting_cash"], 2)

	result = {
		"mode": request["mode"],
		"horizon_months": request["horizon_months"],
		"starting_cash": baseline["starting_cash"],
		"monthly_income": monthly_income,
		"monthly_expenses": monthly_expenses,
		"monthly_savings": monthly_savings,
		"projection_points": projection_points,
		"ending_cash": ending_cash,
		"goal_reached": False,
		"goal_month": None,
		"assumptions": list(baseline["assumptions"]) + [
			"scenario deltas applied additively to declared fields only",
		],
		"warnings": warnings,
		"scenario_delta": request["scenario_delta"],
	}
	result["deterministic_signature"] = build_forecast_signature(result)
	return result



# -------------------- Decision Layer --------------------

def normalize_decision_request(decision_request=None):
	default_request = {
		"mode": "default",
		"include_findings": True,
		"include_actions": True,
		"include_risks": True,
		"include_strengths": True,
		"max_actions": 5,
	}

	if decision_request is None:
		return default_request

	if not isinstance(decision_request, dict):
		raise ValueError("decision_request must be a dict.")

	request = dict(default_request)
	request["mode"] = normalize_text(decision_request.get("mode", default_request["mode"])) or "default"

	for key in ("include_findings", "include_actions", "include_risks", "include_strengths"):
		if key in decision_request:
			request[key] = bool(decision_request.get(key))

	try:
		request["max_actions"] = max(1, int(decision_request.get("max_actions", default_request["max_actions"])))
	except (TypeError, ValueError) as exc:
		raise ValueError("decision_request.max_actions must be an integer.") from exc

	return request


def build_decision_metrics(profile, forecast_bundle=None):
	profile = update_profile_estimates(copy.deepcopy(profile))
	income = round(safe_float(profile.get("estimated_monthly_income", 0.0), 0.0), 2)
	expenses = round(safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0), 2)
	monthly_savings = round(safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0), 2)
	rent = round(safe_float(profile.get("rent", 0.0), 0.0), 2)
	bills_total = round(sum_numeric_values(profile.get("bills", {})), 2)
	extra_expenses_total = round(sum_numeric_values(profile.get("expenses", {})), 2)
	fixed_costs = round(rent + bills_total, 2)
	current_savings = round(extract_starting_cash(profile), 2)
	expense_ranking = build_expense_ranking(profile)

	largest_expense_label = None
	largest_expense_amount = 0.0
	second_largest_expense_label = None
	second_largest_expense_amount = 0.0

	if expense_ranking:
		largest_expense_label, largest_expense_amount = expense_ranking[0]
	if len(expense_ranking) >= 2:
		second_largest_expense_label, second_largest_expense_amount = expense_ranking[1]

	def pct(part, whole):
		if whole <= 0:
			return None
		return round((part / whole) * 100, 2)

	metrics = {
		"monthly_income": income,
		"monthly_expenses": expenses,
		"monthly_savings": monthly_savings,
		"current_savings": current_savings,
		"rent": rent,
		"bills_total": bills_total,
		"extra_expenses_total": extra_expenses_total,
		"fixed_costs": fixed_costs,
		"largest_expense_label": largest_expense_label,
		"largest_expense_amount": round(safe_float(largest_expense_amount, 0.0), 2),
		"second_largest_expense_label": second_largest_expense_label,
		"second_largest_expense_amount": round(safe_float(second_largest_expense_amount, 0.0), 2),
		"monthly_savings_pct_of_income": pct(monthly_savings, income),
		"fixed_costs_pct_of_income": pct(fixed_costs, income),
		"largest_expense_pct_of_income": pct(safe_float(largest_expense_amount, 0.0), income),
		"largest_expense_pct_of_expenses": pct(safe_float(largest_expense_amount, 0.0), expenses),
	}

	if forecast_bundle is not None and isinstance(forecast_bundle, dict):
		metrics["forecast_mode"] = forecast_bundle.get("mode")
		metrics["forecast_starting_cash"] = round(safe_float(forecast_bundle.get("starting_cash", current_savings), current_savings), 2)
		metrics["forecast_ending_cash"] = round(safe_float(forecast_bundle.get("ending_cash", current_savings), current_savings), 2)
		metrics["forecast_goal_reached"] = bool(forecast_bundle.get("goal_reached", False))
		metrics["forecast_goal_month"] = forecast_bundle.get("goal_month")
		metrics["forecast_warnings"] = list(forecast_bundle.get("warnings", []))

	return metrics


def build_decision_signature(payload):
	canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_unique_action(actions, seen_action_codes, action):
	code = str(action.get("code", "")).strip()
	if not code or code in seen_action_codes:
		return
	seen_action_codes.add(code)
	actions.append(action)


def build_decision_bundle(profile, forecast_bundle=None, decision_request=None):
	request = normalize_decision_request(decision_request)
	metrics = build_decision_metrics(profile, forecast_bundle=forecast_bundle)

	findings = []
	actions = []
	risks = []
	strengths = []
	policy_flags = []
	seen_action_codes = set()

	def add_finding(target_list, code, severity, title, message, metric_value, metric_label, trigger_rule, source="profile"):
		record = {
			"code": code,
			"severity": severity,
			"title": title,
			"message": message,
			"metric_value": metric_value,
			"metric_label": metric_label,
			"trigger_rule": trigger_rule,
			"source": source,
		}
		findings.append(record)
		target_list.append(record)
		policy_flags.append(code)
		return record

	monthly_savings = metrics["monthly_savings"]
	monthly_income = metrics["monthly_income"]
	monthly_expenses = metrics["monthly_expenses"]
	fixed_costs = metrics["fixed_costs"]
	fixed_costs_pct = metrics.get("fixed_costs_pct_of_income")
	monthly_savings_pct = metrics.get("monthly_savings_pct_of_income")
	top_label = metrics.get("largest_expense_label") or "expenses"
	top_amount = metrics.get("largest_expense_amount", 0.0)
	top_pct_income = metrics.get("largest_expense_pct_of_income")
	second_label = metrics.get("second_largest_expense_label")
	second_amount = metrics.get("second_largest_expense_amount", 0.0)

	if monthly_savings < 0:
		add_finding(
			risks,
			"negative_cashflow",
			"high",
			"Monthly cashflow is negative.",
			f"Monthly income is {format_money(monthly_income)} and monthly expenses are {format_money(monthly_expenses)}, leaving a deficit of {format_money(abs(monthly_savings))}.",
			round(abs(monthly_savings), 2),
			"monthly_deficit",
			"monthly_savings < 0",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "restore_positive_cashflow",
			"priority": "high",
			"title": "Restore positive monthly cashflow first.",
			"message": f"Reduce recurring outflow or raise income by at least {format_money(abs(monthly_savings))} per month to eliminate the deficit.",
			"linked_finding_codes": ["negative_cashflow"],
			"source": "deterministic_policy",
		})

	if monthly_savings == 0:
		add_finding(
			risks,
			"zero_margin",
			"medium",
			"Monthly cashflow has no margin.",
			f"Monthly income and monthly expenses are both effectively {format_money(monthly_income)}.",
			0.0,
			"monthly_savings",
			"monthly_savings == 0",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "create_positive_margin",
			"priority": "high",
			"title": "Create a positive monthly margin.",
			"message": "Even a small recurring buffer improves resilience and prevents small shocks from forcing a deficit.",
			"linked_finding_codes": ["zero_margin"],
			"source": "deterministic_policy",
		})

	if monthly_savings > 0 and monthly_savings_pct is not None and monthly_savings_pct < DECISION_LOW_MONTHLY_SAVINGS_PCT:
		add_finding(
			risks,
			"low_margin",
			"medium",
			"Monthly savings margin is thin.",
			f"Monthly savings are {format_money(monthly_savings)}, which is {monthly_savings_pct:.2f}% of monthly income.",
			monthly_savings_pct,
			"monthly_savings_pct_of_income",
			f"0 < monthly_savings_pct_of_income < {DECISION_LOW_MONTHLY_SAVINGS_PCT}",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "widen_monthly_margin",
			"priority": "medium",
			"title": "Widen the monthly savings margin.",
			"message": "Focus first on recurring categories so each change compounds every month.",
			"linked_finding_codes": ["low_margin"],
			"source": "deterministic_policy",
		})

	if fixed_costs_pct is not None and fixed_costs_pct >= DECISION_FIXED_COSTS_HIGH_PCT:
		add_finding(
			risks,
			"fixed_cost_concentration",
			"medium",
			"Fixed costs consume a large share of monthly income.",
			f"Fixed monthly costs are {format_money(fixed_costs)} against monthly income of {format_money(monthly_income)}.",
			fixed_costs_pct,
			"fixed_costs_pct_of_income",
			f"fixed_costs_pct_of_income >= {DECISION_FIXED_COSTS_HIGH_PCT}",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "reduce_top_fixed_cost",
			"priority": "high",
			"title": "Reduce the largest fixed-cost line first.",
			"message": f"{top_label.capitalize()} is the largest expense. A reduction there will change monthly savings more than trimming small categories.",
			"linked_finding_codes": ["fixed_cost_concentration"],
			"source": "deterministic_policy",
		})

	if top_pct_income is not None and top_pct_income >= DECISION_TOP_EXPENSE_HIGH_PCT:
		add_finding(
			risks,
			"largest_expense_concentration",
			"medium",
			"The largest expense dominates the budget.",
			f"{top_label.capitalize()} costs {format_money(top_amount)} per month, or {top_pct_income:.2f}% of monthly income.",
			top_pct_income,
			"largest_expense_pct_of_income",
			f"largest_expense_pct_of_income >= {DECISION_TOP_EXPENSE_HIGH_PCT}",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "inspect_largest_expense",
			"priority": "medium",
			"title": "Inspect the largest expense before smaller cuts.",
			"message": f"The biggest leverage point is currently {top_label} at {format_money(top_amount)} per month.",
			"linked_finding_codes": ["largest_expense_concentration"],
			"source": "deterministic_policy",
		})

	if second_amount > 0 and top_amount >= round(second_amount * DECISION_DOMINANCE_RATIO, 2):
		add_finding(
			risks,
			"expense_dominance",
			"medium",
			"One expense line is far above the next-largest category.",
			f"{top_label.capitalize()} at {format_money(top_amount)} is materially larger than {second_label} at {format_money(second_amount)}.",
			round(top_amount / second_amount, 2),
			"largest_to_second_largest_ratio",
			f"largest_expense_amount >= second_largest_expense_amount * {DECISION_DOMINANCE_RATIO}",
		)
		append_unique_action(actions, seen_action_codes, {
			"code": "review_dominant_expense",
			"priority": "medium",
			"title": "Review the dominant expense line first.",
			"message": f"The budget is concentrated in {top_label}, so that line deserves review before scattered minor expenses.",
			"linked_finding_codes": ["expense_dominance"],
			"source": "deterministic_policy",
		})

	if monthly_savings > 0:
		add_finding(
			strengths,
			"positive_surplus",
			"low",
			"Monthly cashflow is positive.",
			f"The profile currently produces {format_money(monthly_savings)} in monthly savings.",
			monthly_savings,
			"monthly_savings",
			"monthly_savings > 0",
		)

	if forecast_bundle is not None and isinstance(forecast_bundle, dict):
		forecast_mode = normalize_text(forecast_bundle.get("mode", ""))
		forecast_starting_cash = round(safe_float(forecast_bundle.get("starting_cash", metrics["current_savings"]), metrics["current_savings"]), 2)
		forecast_ending_cash = round(safe_float(forecast_bundle.get("ending_cash", forecast_starting_cash), forecast_starting_cash), 2)

		if forecast_mode == "goal_eta" and not bool(forecast_bundle.get("goal_reached", False)):
			add_finding(
				risks,
				"forecast_goal_unreachable",
				"high",
				"Forecast goal is not reachable under the current profile.",
				"The current forecast does not reach the requested goal within the active horizon.",
				forecast_bundle.get("goal_month"),
				"goal_month",
				"goal_reached == False",
				source="forecast",
			)
			append_unique_action(actions, seen_action_codes, {
				"code": "increase_goal_delta",
				"priority": "high",
				"title": "Increase the monthly savings delta for the goal.",
				"message": "Either raise monthly income, reduce recurring expenses, or extend the target horizon.",
				"linked_finding_codes": ["forecast_goal_unreachable"],
				"source": "deterministic_policy",
			})

		if forecast_ending_cash < forecast_starting_cash:
			add_finding(
				risks,
				"forecast_drawdown",
				"high",
				"Forecasted cash declines over the projection horizon.",
				f"Projected cash falls from {format_money(forecast_starting_cash)} to {format_money(forecast_ending_cash)}.",
				round(forecast_ending_cash - forecast_starting_cash, 2),
				"forecast_cash_delta",
				"forecast_ending_cash < forecast_starting_cash",
				source="forecast",
			)
			append_unique_action(actions, seen_action_codes, {
				"code": "stop_forecast_drawdown",
				"priority": "high",
				"title": "Stop the projected cash drawdown.",
				"message": "The current trajectory burns cash over time, so recurring inflow or outflow must be adjusted.",
				"linked_finding_codes": ["forecast_drawdown"],
				"source": "deterministic_policy",
			})

	if not request["include_findings"]:
		findings = []
	if not request["include_actions"]:
		actions = []
	if not request["include_risks"]:
		risks = []
	if not request["include_strengths"]:
		strengths = []

	actions = actions[:request["max_actions"]]

	result = {
		"mode": request["mode"],
		"findings": findings,
		"actions": actions,
		"risks": risks,
		"strengths": strengths,
		"metrics_used": metrics,
		"policy_flags": policy_flags,
	}
	result["deterministic_signature"] = build_decision_signature(result)
	return result


def format_decision_bundle(decision_bundle, compact=False):
	if not isinstance(decision_bundle, dict):
		raise ValueError("decision_bundle must be a dict.")

	risks = decision_bundle.get("risks", [])
	actions = decision_bundle.get("actions", [])
	strengths = decision_bundle.get("strengths", [])

	if not risks and not actions and not strengths:
		return "No major deterministic financial issues were detected from the current profile."

	if compact:
		lead = risks[0] if risks else None
		action = actions[0] if actions else None
		strength = strengths[0] if strengths else None

		lead_msg = lead["message"].rstrip(".") if lead else None
		action_msg = action["message"].rstrip(".") if action else None
		strength_msg = strength["message"].rstrip(".") if strength else None

		if lead and action and strength:
			return (
				f"Top risk: {lead_msg}. "
				f"First leverage point: {action_msg}; current strength: {strength_msg.lower()}."
			)

		if lead and action:
			return (
				f"Top risk: {lead_msg}. "
				f"First leverage point: {action_msg}."
			)

		if lead and strength:
			return (
				f"Top risk: {lead_msg}. "
				f"Current strength: {strength_msg.lower()}."
			)

		if lead:
			return f"Top risk: {lead_msg}."

		if action:
			return f"First leverage point: {action_msg}."

		return f"Current strength: {strength_msg.lower()}."

	lines = []

	if risks:
		lead = risks[0]
		lines.append(f"Top finding: {lead['message']}")

	if actions:
		lines.append("Action priorities:")
		for idx, action in enumerate(actions, 1):
			lines.append(f"{idx}. {action['message']}")

	if strengths:
		lines.append(f"Strength to preserve: {strengths[0]['message']}")

	return "\n".join(lines)


def deterministic_actionable_advice(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"actionable advice",
		"give me advice",
		"what should i improve",
		"what should i change",
		"where should i improve",
		"biggest financial risk",
		"financial risks",
		"financial risk",
		"weak point",
		"weak points",
		"what are my weak points",
		"give me actionable advice",
		"what should i do better",
		"qualitative summary",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	decision_bundle = build_decision_bundle(profile)
	compact = (
		"two-sentence" in prompt_l
		or "two sentence" in prompt_l
		or "qualitative summary" in prompt_l
	)
	return format_decision_bundle(decision_bundle, compact=compact)


# -------------------- Deterministic Engine --------------------

def normalize_mutation_key(text):
	text = normalize_text(str(text))
	text = re.sub(r"^(my|the)\s+", "", text)
	text = re.sub(r"[^a-z0-9 -]+", "", text)
	text = re.sub(r"\s+", " ", text).strip()
	text = re.sub(r"\s+(budget|payment|bill|expense|expenses|cost|costs|amount|spending)$", "", text)
	return text.strip()


MUTATION_FIELD_ALIASES = PERSONAL_STANDARD_BILL_ALIASES | {
	"income": ["income", "salary", "pay", "monthly income", "weekly income", "bi-weekly income", "biweekly income", "income amount"],
	"rent": ["rent"],
}


def is_mutation_like_prompt(prompt):
	prompt_l = normalize_text(prompt)

	if not prompt_l:
		return False

	for phrase in [
		"undo last change",
		"undo last update",
		"undo change",
		"revert last change",
		"revert last update",
		"revert change",
	]:
		if phrase in prompt_l:
			return True

	def has_word(word):
		return re.search(rf"\b{re.escape(word)}\b", prompt_l) is not None

	def has_alias_reference():
		for aliases in MUTATION_FIELD_ALIASES.values():
			for alias in aliases:
				alias_n = normalize_mutation_key(alias)
				if alias_n and re.search(rf"\b{re.escape(alias_n)}\b", prompt_l):
					return True
		return False

	def has_domain_keyword():
		for keyword in ["profile", "bill", "expense", "expenses", "category", "budget", "income", "rent"]:
			if re.search(rf"\b{re.escape(keyword)}\b", prompt_l):
				return True
		return False

	if any(has_word(word) for word in ["rename", "remove", "delete", "add", "undo", "revert"]):
		return has_alias_reference() or has_domain_keyword()

	for word in ["replace", "set", "change", "update"]:
		if has_word(word):
			if re.search(r"\b(with|to|=)\b", prompt_l):
				return has_alias_reference() or has_domain_keyword()
			if has_domain_keyword():
				return True

	return False


def build_unsupported_modification_message():
	return (
		"Unsupported modification command. No changes were applied. "
		f"Supported fields currently include {SUPPORTED_MODIFICATION_FIELDS_TEXT}. "
		"Examples: replace rent with 1720; set monthly income to 3500; set weekly income to 900."
	)


def deterministic_undo_last_change(profile, prompt, apply_mutations=True):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"undo last change",
		"undo last update",
		"undo change",
		"revert last change",
		"revert last update",
		"revert change",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	backup = load_profile_backup()
	if not isinstance(backup, dict):
		return "❌ No backup is available to restore."

	backup = update_profile_estimates(backup)

	if not apply_mutations:
		return (
			"Proposed undo (not applied): restore profile from last backup. "
			f"Income would be {format_money(backup.get('estimated_monthly_income', 0.0))}, "
			f"expenses {format_money(backup.get('estimated_monthly_expenses', 0.0))}, "
			f"savings {format_money(backup.get('estimated_monthly_savings', 0.0))}. "
			"Confirm via interactive `eon` menu or call with apply_mutations=True."
		)

	if not save_profile(backup):
		return "❌ Backup was found but could not be restored."

	return (
		f"Last saved change was undone. "
		f"Your estimated monthly income is now {format_money(backup.get('estimated_monthly_income', 0.0))}, "
		f"your total monthly expenses are {format_money(backup.get('estimated_monthly_expenses', 0.0))}, "
		f"and your monthly savings are {format_money(backup.get('estimated_monthly_savings', 0.0))}."
	)


def deterministic_profile_modification(profile, prompt, apply_mutations=True):
	prompt_l = normalize_text(prompt)

	modification_triggers = [
		"replace",
		"set",
		"change",
		"update",
	]

	if not any(word in prompt_l for word in modification_triggers):
		return None

	field_aliases = MUTATION_FIELD_ALIASES

	display_names = {
		"income": "income",
		"rent": "rent",
		"food": "food",
		"car loan": "car loan",
		"phone": "phone",
		"internet": "internet",
		"electricity": "electricity",
		"insurance": "insurance",
		"transport": "transport",
		"subscriptions": "subscriptions",
		"debt": "debt",
		"child support": "child support",
	}

	def parse_amount(text):
		cleaned = str(text).replace(",", "").replace("$", "").strip()
		try:
			return float(cleaned)
		except (TypeError, ValueError):
			return None

	def extract_income_frequency(field_text):
		field_n = normalize_mutation_key(field_text)
		found = []

		if "bi-weekly" in field_n or "biweekly" in field_n:
			found.append("bi-weekly")

		if re.search(r"\bweekly\b", field_n) and "bi-weekly" not in field_n and "biweekly" not in field_n:
			found.append("weekly")

		if "monthly" in field_n:
			found.append("monthly")

		found = list(dict.fromkeys(found))

		if len(found) > 1:
			return None

		if found:
			return found[0]

		return "monthly"

	def find_candidate_fields(text):
		text_n = normalize_mutation_key(text)
		text_tokens = set(text_n.split())
		matches = []

		for canonical, aliases in field_aliases.items():
			for alias in aliases:
				alias_n = normalize_mutation_key(alias)
				alias_tokens = set(alias_n.split())

				if text_n == alias_n:
					matches.append(canonical)
					break

				if text_n.startswith(alias_n + " "):
					matches.append(canonical)
					break

				if text_n.endswith(" " + alias_n):
					matches.append(canonical)
					break

				if alias_tokens and alias_tokens.issubset(text_tokens):
					matches.append(canonical)
					break

		return sorted(set(matches))

	def contains_supported_alias(text):
		return len(find_candidate_fields(text)) > 0

	def apply_update(profile_copy, canonical, value, frequency=None):
		if canonical == "income":
			streams = profile_copy.get("income_streams", [])
			if len(streams) != 1:
				return "Multiple income streams detected. No generic income change was applied. Use Edit Profile instead."

			streams[0]["amount"] = value
			streams[0]["frequency"] = frequency or streams[0].get("frequency", "monthly")
			profile_copy["income_streams"] = streams
			return None

		if canonical == "rent":
			profile_copy["rent"] = value
			return None

		profile_copy.setdefault("bills", {})
		profile_copy.setdefault("expenses", {})

		if canonical in profile_copy["bills"] or canonical in dict(PERSONAL_STANDARD_BILL_PROMPTS):
			profile_copy["bills"][canonical] = value
			profile_copy["bills"] = prune_zero_values(profile_copy["bills"])
			return None

		if canonical in profile_copy["expenses"]:
			profile_copy["expenses"][canonical] = value
			profile_copy["expenses"] = prune_zero_values(profile_copy["expenses"])
			return None

		profile_copy["bills"][canonical] = value
		profile_copy["bills"] = prune_zero_values(profile_copy["bills"])
		return None

	def extract_updates(text):
		updates = []
		parts = re.split(r"\band\b", text, flags=re.IGNORECASE)
		nonempty_parts = []
		income_frequencies = []

		for part in parts:
			part = part.strip(" \t\r\n.,;:!?")
			part = re.sub(r"^(replace|set|change|update)\s+", "", part, flags=re.IGNORECASE)

			if not part:
				continue

			nonempty_parts.append(part)

			match = re.search(
				r"([a-zA-Z_ \-][a-zA-Z0-9_ \-]*?)\s*(?:with|to|=)\s*\$?\s*(-?[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*$",
				part,
				flags=re.IGNORECASE
			)

			if not match:
				if contains_supported_alias(part) or re.search(r"\b(with|to|=)\b", part):
					return None, "Invalid numeric value or incomplete update. No changes were applied."
				continue

			raw_field = match.group(1).strip()
			raw_amount = match.group(2).strip()
			field_key = normalize_mutation_key(raw_field)

			if field_key in GENERIC_AMBIGUOUS_TERMS:
				return None, f"Ambiguous field match for '{raw_field}'. No changes were applied. Be more specific."

			candidates = find_candidate_fields(raw_field)

			if len(candidates) > 1:
				return None, f"Ambiguous field match for '{raw_field}'. No changes were applied. Be more specific."

			if len(candidates) == 0:
				continue

			field = candidates[0]
			amount = parse_amount(raw_amount)

			if amount is None:
				return None, "Invalid numeric value or incomplete update. No changes were applied."

			if amount < 0:
				label = display_names.get(field, field)
				return None, f"Invalid value for {label}: negative amounts are not allowed. No changes were applied."

			frequency = None
			if field == "income":
				frequency = extract_income_frequency(raw_field)
				if frequency is None:
					return None, "Conflicting income frequencies in one command. No changes were applied. Use one income frequency per command."
				income_frequencies.append(frequency)

			updates.append((field, amount, frequency))

		if len(set(income_frequencies)) > 1:
			return None, "Conflicting income frequencies in one command. No changes were applied. Use one income frequency per command."

		if not updates:
			if nonempty_parts and (contains_supported_alias(text) or re.search(r"\b(with|to|=)\b", text, flags=re.IGNORECASE)):
				return None, "No valid updates were found. No changes were applied."
			return [], None

		return updates, None

	def join_changed_parts(parts):
		if len(parts) == 1:
			return parts[0]
		if len(parts) == 2:
			return f"{parts[0]} and {parts[1]}"
		return f"{', '.join(parts[:-1])}, and {parts[-1]}"

	updates, error = extract_updates(prompt)
	if error is not None:
		return error

	if not updates:
		return None

	profile_before = update_profile_estimates(copy.deepcopy(profile))
	profile_copy = copy.deepcopy(profile)
	applied_updates = []

	for field, value, frequency in updates:
		apply_error = apply_update(profile_copy, field, value, frequency)
		if apply_error is not None:
			return apply_error
		applied_updates.append((field, value, frequency))

	profile_copy = update_profile_estimates(profile_copy)
	profile_current = update_profile_estimates(copy.deepcopy(profile))

	if profile_copy == profile_current:
		return "No effective change was applied. The requested values already match the current profile."

	changed_parts = []
	changed_fields = []

	for field, value, frequency in applied_updates:
		changed_fields.append(display_names.get(field, field))
		if field == "income":
			changed_parts.append(f"{frequency} income changed to {format_money(value)}")
		else:
			changed_parts.append(f"{display_names.get(field, field)} changed to {format_money(value)}")

	preview = (
		f"Proposed changes (not applied): {join_changed_parts(changed_parts)}. "
		f"Estimated monthly income would be {format_money(profile_copy.get('estimated_monthly_income', 0.0))}, "
		f"expenses {format_money(profile_copy.get('estimated_monthly_expenses', 0.0))}, "
		f"savings {format_money(profile_copy.get('estimated_monthly_savings', 0.0))}. "
		"Confirm via interactive `eon` menu or call with apply_mutations=True."
	)

	if not apply_mutations:
		return preview

	if not create_profile_backup(profile):
		return "❌ Changes were computed but the pre-change backup could not be saved."

	if not save_profile(profile_copy):
		return "❌ Changes were computed but could not be saved to profile.json."

	journal_ok, journal_error = append_change_journal(
		command=prompt,
		changed_fields=changed_fields,
		before_profile=profile_before,
		after_profile=profile_copy,
	)

	response = (
		f"Saved changes: {join_changed_parts(changed_parts)}. "
		f"Your estimated monthly income is now {format_money(profile_copy.get('estimated_monthly_income', 0.0))}, "
		f"your total monthly expenses are {format_money(profile_copy.get('estimated_monthly_expenses', 0.0))}, "
		f"and your monthly savings are {format_money(profile_copy.get('estimated_monthly_savings', 0.0))}."
	)

	if not journal_ok and journal_error:
		response = f"{response} {journal_error}"

	return response


def deterministic_monthly_summary(profile, prompt):
	prompt_l = normalize_text(prompt)

	if "monthly savings" in prompt_l or "save per month" in prompt_l:
		value = safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0)
		return f"Estimated monthly savings: {format_money(value)}."

	if "monthly income" in prompt_l or "income per month" in prompt_l:
		value = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
		return f"Estimated monthly income: {format_money(value)}."

	if "monthly expenses" in prompt_l or "expenses per month" in prompt_l:
		value = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
		return f"Estimated monthly expenses: {format_money(value)}."

	return None


def deterministic_monthly_spend(profile, prompt):
	prompt_l = normalize_text(prompt)

	if re.search(r"\b(rename|remove|delete|add|replace|set|change|update|undo|revert)\b", prompt_l):
		return None

	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	rent = safe_float(profile.get("rent", 0.0), 0.0)
	bills_total = sum_numeric_values(profile.get("bills", {}))
	total_expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)

	if (
		"left after all expenses" in prompt_l
		or "money left after all expenses" in prompt_l
		or "disposable income" in prompt_l
	):
		left = income - total_expenses
		return (
			f"You have {format_money(left)} left after all expenses. "
			f"(Income: {format_money(income)}, total expenses: {format_money(total_expenses)})"
		)

	if (
		"left after rent and bills" in prompt_l
		or "money left after rent and bills" in prompt_l
		or "left after fixed costs" in prompt_l
		or "money left after fixed costs" in prompt_l
		or "left after essentials" in prompt_l
		or "money left after essentials" in prompt_l
	):
		left = income - rent - bills_total
		return (
			f"You have {format_money(left)} left after rent and bills. "
			f"(Income: {format_money(income)}, rent: {format_money(rent)}, bills: {format_money(bills_total)})"
		)

	label, value = get_aggregate_amount(profile, prompt)
	if label is not None:
		return f"You spend {format_money(value)} per month on {label}."

	category = detect_category_from_prompt(prompt)
	if category is not None:
		value = get_profile_category_amount(profile, category)
		return f"You spend {format_money(value)} per month on {category}."

	return None


def deterministic_income_ratio(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"percentage of my income",
		"percent of my income",
		"how much of my income",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)

	if income <= 0:
		return "Cannot compute percentage: income is zero or undefined."

	label, value = get_aggregate_amount(profile, prompt)

	if label is None:
		category = detect_category_from_prompt(prompt)
		if category is None:
			return None
		label = category
		value = get_profile_category_amount(profile, category)

	percentage = (value / income) * 100

	return (
		f"{percentage:.2f}% of your income goes to {label}. "
		f"(Monthly income: {format_money(income)}, {label}: {format_money(value)})"
	)


def deterministic_savings_target(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"when will i have",
		"when will i reach",
		"how long until",
		"how many months until",
		"how long to reach",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	target = parse_target_amount(prompt)
	if target is None:
		return None

	forecast = forecast_goal_eta(
		profile,
		goal_amount=target,
		overrides={"starting_cash_override": extract_current_savings(profile, prompt)},
	)
	current_savings = forecast["starting_cash"]
	monthly_savings = forecast["monthly_savings"]

	if target <= current_savings:
		return (
			f"You have already reached that target. "
			f"Current savings considered: {format_money(current_savings)}. "
			f"Target: {format_money(target)}."
		)

	if monthly_savings <= 0:
		return (
			f"You will not reach {format_money(target)} under the current profile because "
			f"estimated monthly savings are {format_money(monthly_savings)}."
		)

	months = safe_float(forecast.get("exact_months_to_goal"), 0.0)
	whole_months = forecast.get("goal_month")
	years = months / 12

	return (
		f"Assuming current savings of {format_money(current_savings)} and monthly savings of "
		f"{format_money(monthly_savings)}, you will reach {format_money(target)} in about "
		f"{months:.1f} months, which is approximately {years:.2f} years. "
		f"Rounded up to whole months: {whole_months} months."
	)


def deterministic_future_savings(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"how much will i have",
		"how much savings will i have",
		"what will my savings be",
		"how much money will i have saved",
		"how much will i have left after",
		"how much money will i have left after",
		"what will i have left after",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	months = parse_time_horizon_months(prompt)
	if months is None:
		return None

	horizon_months = int(math.ceil(months))
	forecast = forecast_baseline(
		profile,
		horizon_months=horizon_months,
		overrides={"starting_cash_override": extract_current_savings(profile, prompt)},
	)
	current_savings = forecast["starting_cash"]
	monthly_savings = forecast["monthly_savings"]
	future_savings = forecast["ending_cash"]
	years = months / 12
	month_note = ""
	if abs(months - horizon_months) > 1e-9:
		month_note = f" using a rounded projection horizon of {horizon_months} months"

	if "left after" in prompt_l:
		return (
			f"If nothing changes, you will have about {format_money(future_savings)} left "
			f"after {months:.1f} months ({years:.2f} years){month_note}. "
			f"(Current savings: {format_money(current_savings)}, monthly savings: {format_money(monthly_savings)})"
		)

	return (
		f"Assuming current savings of {format_money(current_savings)} and monthly savings of "
		f"{format_money(monthly_savings)}, you will have about {format_money(future_savings)} "
		f"after {months:.1f} months ({years:.2f} years){month_note}."
	)


def deterministic_affordability(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"can i afford",
		"is it affordable",
		"could i afford",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	cost = parse_money_value(prompt)
	if cost is None:
		return None

	current_savings = extract_current_savings(profile, prompt)
	monthly_savings = safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0)

	if current_savings >= cost:
		return (
			f"Yes. Based on current savings considered at {format_money(current_savings)}, "
			f"you can already cover {format_money(cost)}."
		)

	if monthly_savings <= 0:
		return (
			f"No. You do not currently cover {format_money(cost)} with savings of {format_money(current_savings)}, "
			f"and estimated monthly savings are {format_money(monthly_savings)}."
		)

	remaining = cost - current_savings
	months = remaining / monthly_savings
	whole_months = math.ceil(months)

	return (
		f"Not immediately. With current savings of {format_money(current_savings)} and monthly savings of "
		f"{format_money(monthly_savings)}, you would need about {months:.1f} months "
		f"(rounded up: {whole_months} months) to cover {format_money(cost)}."
	)


def deterministic_cashflow_state(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"am i overspending",
		"am i in deficit",
		"am i in surplus",
		"is my budget positive",
		"is my cashflow positive",
		"is my cash flow positive",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
	savings = safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0)

	if income <= 0 and expenses <= 0:
		return "Cannot assess budget state: income and expenses are both undefined or zero."

	if savings < 0:
		deficit = abs(savings)
		return (
			f"You are overspending by {format_money(deficit)} per month. "
			f"(Income: {format_money(income)}, expenses: {format_money(expenses)})"
		)

	if savings == 0:
		return (
			f"Your budget is exactly balanced. "
			f"(Income: {format_money(income)}, expenses: {format_money(expenses)}, monthly savings: $0.00)"
		)

	return (
		f"You are not overspending. You are saving {format_money(savings)} per month. "
		f"(Income: {format_money(income)}, expenses: {format_money(expenses)})"
	)


def deterministic_biggest_expense(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"biggest expense",
		"largest expense",
		"highest expense",
		"biggest expenses",
		"largest expenses",
		"highest expenses",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	ranking = build_expense_ranking(profile)
	if not ranking:
		return "No expenses found in profile."

	if "expenses" in prompt_l and not ("biggest expense" in prompt_l or "largest expense" in prompt_l or "highest expense" in prompt_l):
		top = ranking[:3]
		parts = [f"{label}: {format_money(value)}" for label, value in top]
		return f"Top expenses: {', '.join(parts)}."

	label, value = ranking[0]
	return f"Your largest expense is {label} at {format_money(value)} per month."


def deterministic_credit_category(prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"how much did i spend",
		"how much have i spent",
		"how much was spent",
		"what did i spend",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	category = detect_category_from_prompt(prompt)
	if category is None:
		return None

	transactions = load_mastercard_summary()
	if transactions is None:
		return "❌ mastercard_summary.json not found."

	category_totals = build_credit_categories(transactions)
	value = safe_float(category_totals.get(category, 0.0), 0.0)

	return f"Recorded credit-card spending for category '{category}': {format_money(value)}."


def deterministic_scenario_simulation(profile, prompt):
	prompt_l = normalize_text(prompt)

	if "what happens if" not in prompt_l and "what if" not in prompt_l:
		return None

	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	current_rent = safe_float(profile.get("rent", 0.0), 0.0)
	current_expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)

	changes = 0
	new_income = income
	new_rent = current_rent
	new_expenses = current_expenses

	rent_match = re.search(r"rent increases by\s+\$?\s*([0-9]+(?:[.,][0-9]{1,2})?)", prompt_l)
	if rent_match:
		rent_delta = safe_float(rent_match.group(1).replace(",", ""), 0.0)
		new_rent += rent_delta
		new_expenses += rent_delta
		changes += 1

	income_match = re.search(r"income drops by\s+\$?\s*([0-9]+(?:[.,][0-9]{1,2})?)", prompt_l)
	if income_match:
		income_delta = safe_float(income_match.group(1).replace(",", ""), 0.0)
		new_income -= income_delta
		changes += 1

	if changes == 0:
		return None

	new_savings = new_income - new_expenses

	return (
		f"Under that scenario, your monthly income would be {format_money(new_income)}, "
		f"your rent would be {format_money(new_rent)}, "
		f"your total monthly expenses would be {format_money(new_expenses)}, "
		f"and your monthly savings would become {format_money(new_savings)}."
	)


def deterministic_break_even(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"how much can my rent increase",
		"max rent increase",
		"maximum rent increase",
		"before i start overspending",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
	savings = income - expenses

	if savings <= 0:
		return (
			f"You are already overspending by {format_money(abs(savings))} per month. "
			f"There is no margin for rent increase."
		)

	return (
		f"Your rent can increase by up to {format_money(savings)} before you start overspending. "
		f"Beyond that, your monthly savings would fall below $0.00."
	)


def deterministic_offset_requirement(profile, prompt):
	prompt_l = normalize_text(prompt)

	trigger_words = [
		"how much would my income need to increase",
		"how much would income need to increase",
		"to offset",
	]

	if not any(word in prompt_l for word in trigger_words):
		return None

	if "rent increase" not in prompt_l and "rent increases" not in prompt_l:
		return None

	amount = parse_money_value(prompt)
	if amount is None:
		return None

	return (
		f"Your income would need to increase by {format_money(amount)} per month "
		f"to fully offset a rent increase of {format_money(amount)} per month."
	)


def run_deterministic_engine(profile, prompt, apply_mutations=True):
	mutation_handlers = [
		deterministic_undo_last_change,
		deterministic_profile_modification,
	]

	non_mutation_handlers = [
		deterministic_monthly_summary,
		deterministic_income_ratio,
		deterministic_scenario_simulation,
		deterministic_monthly_spend,
		deterministic_savings_target,
		deterministic_future_savings,
		deterministic_affordability,
		deterministic_cashflow_state,
		deterministic_actionable_advice,
		deterministic_biggest_expense,
		deterministic_credit_category,
		deterministic_offset_requirement,
		deterministic_break_even,
	]

	for handler in mutation_handlers:
		try:
			result = handler(profile, prompt, apply_mutations=apply_mutations)
			if result is not None:
				return result
		except TypeError:
			try:
				result = handler(profile, prompt)
				if result is not None:
					return result
			except Exception:
				continue
		except Exception:
			continue

	if is_mutation_like_prompt(prompt):
		return build_unsupported_modification_message()

	for handler in non_mutation_handlers:
		try:
			result = handler(profile, prompt)
			if result is not None:
				return result
		except Exception:
			continue

	return None


# -------------------- Model Layer --------------------

def list_available_local_models():
	from eon.local_models import discover_gguf_models

	return discover_gguf_models(MODELS_DIR)


def recommend_local_model(models=None):
	from eon.local_models import discover_gguf_models, recommend_best_model

	candidates = models if models is not None else discover_gguf_models(MODELS_DIR)
	return recommend_best_model(candidates)


def select_local_model_interactive():
	"""List replaceable GGUF tools, mark one best-fit suggestion, let the user choose."""
	global MODEL_PATH
	global LLM

	from eon.local_models import format_model_choice_menu

	env_override = os.getenv("EON_PFA_MODEL_PATH")
	if env_override:
		override_path = Path(env_override)
		if override_path.exists():
			if MODEL_PATH != override_path:
				LLM = None
			MODEL_PATH = override_path
			print(f"Using EON_PFA_MODEL_PATH override: {MODEL_PATH}")
			return MODEL_PATH
		print(f"⚠️ EON_PFA_MODEL_PATH is set but missing: {override_path}")
		print("Falling back to discovered local GGUF models (if any).")

	models = list_available_local_models()
	suggested = recommend_local_model(models)
	print(format_model_choice_menu(models, suggested))

	if not models:
		print("")
		print(f"❌ No runnable GGUF models found in {MODELS_DIR}")
		print("Place one or more .gguf files there, or set EON_PFA_MODEL_PATH.")
		print("Models are replaceable tools — EON will not download one.")
		return None

	if len(models) == 1:
		chosen = models[0]
		print(f"\nOnly one model available — selecting {chosen.name}.")
	else:
		default_index = 1
		if suggested is not None:
			for index, model in enumerate(models, start=1):
				if model.path == suggested.path:
					default_index = index
					break
		raw = input(
			f"Select model [1-{len(models)}] (Enter = suggested #{default_index}): "
		).strip()
		if not raw:
			chosen = models[default_index - 1]
		else:
			try:
				index = int(raw)
			except ValueError:
				print("❌ Invalid selection.")
				return None
			if index < 1 or index > len(models):
				print("❌ Invalid selection.")
				return None
			chosen = models[index - 1]

	if MODEL_PATH != chosen.path:
		LLM = None
	MODEL_PATH = chosen.path
	print(f"Selected Local AI model: {MODEL_PATH.name}")
	return MODEL_PATH


def get_llm(model_path=None):
	global LLM
	global MODEL_PATH

	if Llama is None:
		print("❌ llama_cpp is not installed in the active environment.")
		return None

	target = Path(model_path) if model_path is not None else MODEL_PATH

	if LLM is not None and target.exists() and str(target) == str(MODEL_PATH):
		return LLM

	if not target.exists() or target.name == ".no_gguf_discovered":
		available = list_available_local_models()
		if available:
			suggested = recommend_local_model(available)
			print("❌ No model selected yet. Available replaceable GGUF tools:")
			for model in available:
				marker = " ← suggested" if suggested and model.path == suggested.path else ""
				print(f"  - {model.name} ({model.size_label()}){marker}")
			if suggested is not None:
				print(f"Suggested best fit: {suggested.name}")
				print("Why: " + "; ".join(suggested.reasons))
		else:
			print(f"❌ No runnable GGUF models found in {MODELS_DIR}")
			print("Place a .gguf file there or set EON_PFA_MODEL_PATH. EON will not download a model.")
		return None

	print(f"🔄 Initializing GGUF model ({target.name})...")

	try:
		LLM = Llama(
			model_path=str(target),
			n_ctx=DEFAULT_CTX,
			n_threads=DEFAULT_THREADS,
			n_gpu_layers=DEFAULT_GPU_LAYERS,
			verbose=False,
		)
		MODEL_PATH = target
	except Exception as e:
		print(f"❌ Error loading model: {e}")
		LLM = None
		return None

	return LLM


def build_profile_llm_grounding(profile):
	profile = update_profile_estimates(copy.deepcopy(profile))
	income = safe_float(profile.get("estimated_monthly_income", 0.0), 0.0)
	expenses = safe_float(profile.get("estimated_monthly_expenses", 0.0), 0.0)
	monthly_savings = safe_float(profile.get("estimated_monthly_savings", 0.0), 0.0)
	rent = safe_float(profile.get("rent", 0.0), 0.0)
	bills_total = sum_numeric_values(profile.get("bills", {}))
	extra_expenses_total = sum_numeric_values(profile.get("expenses", {}))
	fixed_costs = round(rent + bills_total, 2)
	current_savings = extract_current_savings(profile, "")
	ranking = build_expense_ranking(profile)
	top_label, top_amount = (ranking[0] if ranking else ("expenses", expenses))

	def pct(part, whole):
		if whole <= 0:
			return None
		return round((part / whole) * 100, 2)

	grounding = {
		"monthly_income": round(income, 2),
		"monthly_expenses": round(expenses, 2),
		"monthly_savings": round(monthly_savings, 2),
		"current_savings": round(current_savings, 2),
		"rent": round(rent, 2),
		"bills_total": round(bills_total, 2),
		"extra_expenses_total": round(extra_expenses_total, 2),
		"fixed_costs": round(fixed_costs, 2),
		"largest_expense_label": str(top_label),
		"largest_expense_amount": round(safe_float(top_amount, 0.0), 2),
	}

	percentage_fields = {
		"monthly_savings_pct_of_income": pct(monthly_savings, income),
		"rent_pct_of_income": pct(rent, income),
		"fixed_costs_pct_of_income": pct(fixed_costs, income),
		"largest_expense_pct_of_income": pct(safe_float(top_amount, 0.0), income),
		"largest_expense_pct_of_expenses": pct(safe_float(top_amount, 0.0), expenses),
	}

	for key, value in percentage_fields.items():
		if value is not None:
			grounding[key] = value

	return grounding



def build_grounded_profile_ai_fallback(profile, prompt):
	grounding = build_profile_llm_grounding(profile)
	prompt_l = normalize_text(prompt)
	monthly_income = safe_float(grounding.get("monthly_income", 0.0), 0.0)
	monthly_expenses = safe_float(grounding.get("monthly_expenses", 0.0), 0.0)
	monthly_savings = safe_float(grounding.get("monthly_savings", 0.0), 0.0)
	fixed_costs = safe_float(grounding.get("fixed_costs", 0.0), 0.0)
	top_label = grounding.get("largest_expense_label", "expenses")
	top_amount = safe_float(grounding.get("largest_expense_amount", 0.0), 0.0)
	top_pct_income = grounding.get("largest_expense_pct_of_income")

	if monthly_savings < 0:
		sentence_one = (
			f"Your main weak point is that the current profile runs a monthly deficit of "
			f"{format_money(abs(monthly_savings))}."
		)
		sentence_two = (
			f"Monthly income is {format_money(monthly_income)}, monthly expenses are {format_money(monthly_expenses)}, "
			f"and {top_label} is your largest expense at {format_money(top_amount)}."
		)
		return f"{sentence_one} {sentence_two}"

	if any(phrase in prompt_l for phrase in ["weak point", "weak points", "risk", "risks", "qualitative summary"]):
		if top_pct_income is not None:
			sentence_one = (
				f"Your main weak point is cost concentration: {top_label} is your largest monthly expense at "
				f"{format_money(top_amount)}, which is {top_pct_income:.2f}% of monthly income."
			)
		else:
			sentence_one = (
				f"Your main weak point is cost concentration: {top_label} is your largest monthly expense at "
				f"{format_money(top_amount)}."
			)
		sentence_two = (
			f"Fixed monthly costs total {format_money(fixed_costs)}, leaving {format_money(monthly_savings)} "
			f"in monthly savings under the current profile."
		)
		return f"{sentence_one} {sentence_two}"

	return (
		f"Monthly income is {format_money(monthly_income)}, monthly expenses are {format_money(monthly_expenses)}, "
		f"and monthly savings are {format_money(monthly_savings)}. "
		f"Your largest expense is {top_label} at {format_money(top_amount)}, while fixed monthly costs total {format_money(fixed_costs)}."
	)



def build_system_prompt():
	return (
		"You are a local personal financial assistant. "
		"Answer clearly, precisely, and practically. "
		"Do not mention being an AI. "
		"Do not repeat the user's question. "
		"If enough numeric data is provided, compute directly. "
		"If data is insufficient, state exactly what is missing. "
		"Use only the numeric values provided in the grounding metrics and context. "
		"Do not invent benchmarks, recommended ranges, standards, norms, or external rules unless they are explicitly provided. "
		"If you use a percentage or amount, it must come directly from the provided data or from simple arithmetic based on it. "
		"Be concise but useful."
	)



def build_allowed_percentage_strings(grounding_data):
	allowed = set()

	def add_value(value):
		if value is None:
			return

		try:
			numeric = float(value)
		except (TypeError, ValueError):
			return

		for formatted in {
			f"{numeric:.0f}",
			f"{numeric:.1f}",
			f"{numeric:.2f}",
		}:
			allowed.add(formatted)

	def walk(value):
		if isinstance(value, dict):
			for key, nested in value.items():
				if isinstance(key, str) and ("pct" in key or "percent" in key):
					add_value(nested)
				walk(nested)
		elif isinstance(value, list):
			for nested in value:
				walk(nested)

	walk(grounding_data)
	return allowed



BENCHMARK_GUARD_BLOCKED_PHRASES = [
	"recommended",
	"ideal",
	"standard",
	"normal",
	"healthy",
	"best practice",
	"rule of thumb",
]


def classify_llm_response(response, grounding_data=None):
	"""Apply the "no invented benchmarks" guard and report why it fired.

	Returns ``(clean_response, guard_reason)``. ``guard_reason`` is ``None``
	when the response passes; otherwise it names the exact rejection cause so
	the guard is observable (operator notice + task log), instead of silently
	swapping in a fallback.
	"""
	response = re.sub(r"\s{2,}", " ", str(response or "").strip()).strip()
	if not response:
		return None, "empty response"

	if grounding_data is None:
		return response, None

	response_l = normalize_text(response)
	for phrase in BENCHMARK_GUARD_BLOCKED_PHRASES:
		if phrase in response_l:
			return None, f"blocked phrase: '{phrase}'"

	allowed_percentages = build_allowed_percentage_strings(grounding_data)
	for pct in re.findall(r"(-?[0-9]+(?:\.[0-9]+)?)\s*%", response):
		if pct not in allowed_percentages:
			return None, f"unsupported percentage: {pct}%"

	return response, None


def sanitize_llm_response(response, grounding_data=None):
	clean, _guard_reason = classify_llm_response(response, grounding_data)
	return clean



def ask_llm(prompt, context_label, context_data, grounding_data=None, fallback_response=None):
	"""Run the optional local model and apply the benchmark guard.

	Returns a structured dict so callers can surface and audit *why* an answer
	was produced or discarded:
	``{text, routing, benchmark_guard_applied, guard_reason, backend_used}``.
	"""
	llm = get_llm()
	if llm is None:
		return {
			"text": fallback_response or "❌ Local AI unavailable: model or runtime environment is not configured.",
			"routing": "llm_unavailable",
			"benchmark_guard_applied": False,
			"guard_reason": None,
			"backend_used": False,
		}

	system_prompt = build_system_prompt()
	full_prompt = (
		"[INST] " + system_prompt + "\n"
		f"User question: {prompt}\n"
		f"Grounding metrics: {json.dumps(grounding_data or {}, ensure_ascii=False)}\n"
		f"{context_label}: {json.dumps(context_data, ensure_ascii=False)}\n"
		"[/INST]"
	)

	try:
		output = llm(
			full_prompt,
			max_tokens=256,
			temperature=0.2,
			top_p=0.9,
			stop=["</s>", "<|im_end|>"],
		)
		raw = output["choices"][0]["text"].strip()
		clean, guard_reason = classify_llm_response(raw, grounding_data)

		if clean:
			return {
				"text": clean,
				"routing": "llm",
				"benchmark_guard_applied": False,
				"guard_reason": None,
				"backend_used": True,
			}

		guard_applied = guard_reason != "empty response"
		return {
			"text": fallback_response or "❌ Model response was discarded because it included unsupported claims.",
			"routing": "llm_sanitized_fallback" if guard_applied else "llm_empty",
			"benchmark_guard_applied": guard_applied,
			"guard_reason": guard_reason,
			"backend_used": True,
		}
	except Exception as e:
		return {
			"text": fallback_response or f"❌ AI error: {e}",
			"routing": "llm_error",
			"benchmark_guard_applied": False,
			"guard_reason": str(e),
			"backend_used": True,
		}


# -------------------- View / Reporting --------------------

def render_profile_charts(profile):
	paths = []

	profile_budget_path = REPORTS_DIR / "profile_budget_pie.png"
	profile_chart = build_pie_chart(
		build_profile_budget_categories(profile),
		"Monthly Budget Breakdown",
		profile_budget_path,
	)
	if profile_chart is not None:
		paths.append(profile_chart)

	transactions = load_mastercard_summary()
	if transactions:
		credit_chart = build_pie_chart(
			build_credit_categories(transactions),
			"Credit Card Spending Breakdown",
			REPORTS_DIR / "credit_spending_pie.png",
		)
		if credit_chart is not None:
			paths.append(credit_chart)

	return paths


# -------------------- UI Actions --------------------

def create_new_profile_action():
	create_new_profile()


def view_profile():
	profile = load_profile()

	if not profile:
		print(profile_missing_message())
		return

	profile = update_profile_estimates(profile)
	save_profile(profile)

	print(build_profile_summary_text(profile))

	paths = render_profile_charts(profile)
	if paths:
		print("\n📈 Generated chart files:")
		for chart_path in paths:
			print(f" - {chart_path}")
	else:
		print("\n⚠️ No chart data available yet.")


def ask_local_ai(prompt):
	import sys
	from datetime import datetime, timezone

	from eon.task_log import ToolCallRecord, record_task_log

	started = datetime.now(timezone.utc)
	engine_module = sys.modules[__name__]

	def _log(result, tools):
		try:
			record_task_log(
				prompt=prompt,
				result=result,
				tools_called=tools,
				started_at=started,
				finished_at=datetime.now(timezone.utc),
				caller="menu",
				agent="finance",
				engine=engine_module,
			)
		except Exception:
			pass

	profile, profile_error = get_profile_context()
	if profile_error:
		print(profile_error)
		_log(
			{"status": "no_profile", "routing": "blocked", "answer": profile_error},
			[ToolCallRecord(tool="eon.get_profile_context", status="failed", detail=profile_error)],
		)
		return

	deterministic_answer = run_deterministic_engine(profile, prompt)
	if deterministic_answer is not None:
		print("\n🤖", deterministic_answer)
		_log(
			{
				"status": "ok",
				"routing": "deterministic",
				"answer": deterministic_answer,
				"profile_type": profile.get("type"),
			},
			[ToolCallRecord(
				tool="eon.run_deterministic_engine",
				status="ok",
				detail=deterministic_answer,
				routing="deterministic",
			)],
		)
		return

	prompt_l = normalize_text(prompt)

	if "credit" in prompt_l or "mastercard" in prompt_l:
		credit_data, credit_error = get_credit_context(limit=50)
		if credit_error:
			print(credit_error)
			_log(
				{"status": "blocked", "routing": "blocked", "answer": credit_error},
				[ToolCallRecord(tool="eon.get_credit_context", status="failed", detail=credit_error)],
			)
			return
		llm_result = ask_llm(
			prompt,
			"Recent Mastercard Transactions",
			credit_data,
			fallback_response="❌ Local AI unavailable: could not answer credit spending questions without model support.",
		)
	else:
		grounding_data = build_profile_llm_grounding(profile)
		fallback_response = build_grounded_profile_ai_fallback(profile, prompt)
		llm_result = ask_llm(
			prompt,
			"Financial Profile",
			profile,
			grounding_data=grounding_data,
			fallback_response=fallback_response,
		)

	response = llm_result.get("text")
	routing = llm_result.get("routing", "llm")
	guard_applied = bool(llm_result.get("benchmark_guard_applied"))
	guard_reason = llm_result.get("guard_reason")

	if not response:
		print("\n❌ Local AI could not produce a safe response.")
	else:
		if guard_applied:
			print(
				f"\n🛡️  No-invented-benchmarks guard applied ({guard_reason}); "
				"returning a grounded answer instead of the model's claim."
			)
		print("\n🤖", response)

	status = "ok"
	if routing == "llm_unavailable":
		status = "requires_ai"
	elif routing == "llm_error":
		status = "error"

	tool_status = "ok"
	if guard_applied:
		tool_status = "blocked"
	elif routing in ("llm_error", "llm_unavailable"):
		tool_status = "failed"

	_log(
		{
			"status": status,
			"routing": routing,
			"answer": response,
			"profile_type": profile.get("type"),
			"benchmark_guard_applied": guard_applied,
			"guard_reason": guard_reason,
		},
		[ToolCallRecord(
			tool="eon.ask_llm",
			status=tool_status,
			detail=guard_reason or response,
			routing=routing,
		)],
	)


# -------------------- Regression Harness --------------------

def run_regression_tests():
	global BASE_DIR
	global FINANCE_DIR
	global REPORTS_DIR
	global PROFILE_PATH
	global PROFILE_BACKUP_PATH
	global SUMMARY_PATH
	global CHANGE_JOURNAL_PATH

	original_base_dir = BASE_DIR
	original_finance_dir = FINANCE_DIR
	original_reports_dir = REPORTS_DIR
	original_profile_path = PROFILE_PATH
	original_backup_path = PROFILE_BACKUP_PATH
	original_summary_path = SUMMARY_PATH
	original_change_journal_path = CHANGE_JOURNAL_PATH

	temp_root = Path(tempfile.mkdtemp(prefix="financial_agent_regression_"))
	temp_finance_dir = temp_root / "finance"
	temp_reports_dir = temp_finance_dir / "reports"
	temp_finance_dir.mkdir(parents=True, exist_ok=True)
	temp_reports_dir.mkdir(parents=True, exist_ok=True)

	try:
		BASE_DIR = temp_root
		FINANCE_DIR = temp_finance_dir
		REPORTS_DIR = temp_reports_dir
		PROFILE_PATH = FINANCE_DIR / "profile.json"
		PROFILE_BACKUP_PATH = FINANCE_DIR / "profile_last_backup.json"
		SUMMARY_PATH = FINANCE_DIR / "mastercard_summary.json"
		CHANGE_JOURNAL_PATH = FINANCE_DIR / "change_journal.csv"

		seed_profile = {
			"type": "personal",
			"income_streams": [
				{
					"name": "Primary income",
					"amount": 1800,
					"frequency": "bi-weekly",
				},
			],
			"rent": 1700,
			"bills": {
				"car loan": 325,
				"phone": 25,
				"electricity": 50,
				"food": 400,
				"insurance": 100,
				"subscriptions": 40,
				"child support": 450,
			},
			"expenses": {},
		}

		write_json(PROFILE_PATH, update_profile_estimates(seed_profile))
		write_json(SUMMARY_PATH, [])

		failures = []
		passes = 0

		def check_equal(name, actual, expected):
			nonlocal passes
			if actual == expected:
				print(f"[PASS] {name}")
				passes += 1
			else:
				print(f"[FAIL] {name}")
				print(f"  expected: {expected}")
				print(f"  actual:   {actual}")
				failures.append(name)

		def current_profile():
			profile = load_profile()
			if profile is None:
				raise SystemExit("Regression harness failed: could not load temp profile.")
			profile = update_profile_estimates(profile)
			save_profile(profile)
			return profile

		grounding = build_profile_llm_grounding(current_profile())

		check_equal(
			"grounding savings ratio computed",
			grounding.get("monthly_savings_pct_of_income"),
			20.77
		)

		check_equal(
			"supported grounding percentage allowed",
			sanitize_llm_response("Rent is 43.59% of your monthly income.", grounding),
			"Rent is 43.59% of your monthly income."
		)

		check_equal(
			"unsupported benchmark claim rejected",
			sanitize_llm_response(
				"Your savings rate is 43.15% of your income, which is below the recommended savings rate of 20%.",
				grounding,
			),
			None
		)

		check_equal(
			"monthly expenses summary",
			run_deterministic_engine(current_profile(), "what are my monthly expenses?"),
			"Estimated monthly expenses: $3090.00."
		)

		check_equal(
			"negative rent rejected",
			run_deterministic_engine(current_profile(), "replace rent with -50"),
			"Invalid value for rent: negative amounts are not allowed. No changes were applied."
		)

		check_equal(
			"malformed numeric rejected",
			run_deterministic_engine(current_profile(), "replace rent with abc"),
			"Invalid numeric value or incomplete update. No changes were applied."
		)

		check_equal(
			"ambiguous field rejected",
			run_deterministic_engine(current_profile(), "replace bill with 50"),
			"Ambiguous field match for 'bill'. No changes were applied. Be more specific."
		)

		check_equal(
			"conflicting income frequencies rejected",
			run_deterministic_engine(current_profile(), "set weekly income to 900 and monthly income to 3500"),
			"Conflicting income frequencies in one command. No changes were applied. Use one income frequency per command."
		)

		check_equal(
			"unsupported rename blocked",
			run_deterministic_engine(current_profile(), "rename groceries to food"),
			build_unsupported_modification_message()
		)

		check_equal(
			"scenario routing",
			run_deterministic_engine(current_profile(), "what happens if rent increases by 100"),
			"Under that scenario, your monthly income would be $3900.00, your rent would be $1800.00, your total monthly expenses would be $3190.00, and your monthly savings would become $710.00."
		)


		baseline_forecast = forecast_baseline(current_profile(), horizon_months=3)
		check_equal(
			"forecast baseline ending cash",
			baseline_forecast["ending_cash"],
			2430.0
		)

		check_equal(
			"forecast baseline deterministic signature stable",
			baseline_forecast["deterministic_signature"] == forecast_baseline(current_profile(), horizon_months=3)["deterministic_signature"],
			True
		)

		goal_forecast = forecast_goal_eta(current_profile(), goal_amount=3000)
		check_equal(
			"forecast goal eta whole months",
			goal_forecast["goal_month"],
			4
		)

		scenario_forecast = forecast_scenario(current_profile(), horizon_months=2, scenario_delta={"rent": 100})
		check_equal(
			"forecast scenario monthly savings",
			scenario_forecast["monthly_savings"],
			710.0
		)

		decision_bundle = build_decision_bundle(current_profile())
		check_equal(
			"decision bundle fixed cost flag present",
			"fixed_cost_concentration" in decision_bundle["policy_flags"],
			True
		)

		check_equal(
			"decision bundle top action code",
			decision_bundle["actions"][0]["code"],
			"reduce_top_fixed_cost"
		)

		check_equal(
			"actionable advice routed deterministically",
			run_deterministic_engine(current_profile(), "give me actionable advice"),
			"Top finding: Fixed monthly costs are $3090.00 against monthly income of $3900.00.\nAction priorities:\n1. Rent is the largest expense. A reduction there will change monthly savings more than trimming small categories.\n2. The biggest leverage point is currently rent at $1700.00 per month.\n3. The budget is concentrated in rent, so that line deserves review before scattered minor expenses.\nStrength to preserve: The profile currently produces $810.00 in monthly savings."
		)

		check_equal(
			"compact weak points summary routed deterministically",
			run_deterministic_engine(current_profile(), "give me a two-sentence qualitative summary of my current financial weak points"),
			"Top risk: Fixed monthly costs are $3090.00 against monthly income of $3900.00. First leverage point: Rent is the largest expense. A reduction there will change monthly savings more than trimming small categories; current strength: the profile currently produces $810.00 in monthly savings."
		)

		check_equal(
			"valid rent update saved",
			run_deterministic_engine(current_profile(), "replace rent with 1810"),
			"Saved changes: rent changed to $1810.00. Your estimated monthly income is now $3900.00, your total monthly expenses are $3200.00, and your monthly savings are $700.00."
		)

		check_equal(
			"journal row count after saved change",
			count_change_journal_entries(),
			1
		)

		check_equal(
			"no-op does not save",
			run_deterministic_engine(current_profile(), "replace rent with 1810"),
			"No effective change was applied. The requested values already match the current profile."
		)

		check_equal(
			"journal row count unchanged after no-op",
			count_change_journal_entries(),
			1
		)

		check_equal(
			"undo last change",
			run_deterministic_engine(current_profile(), "undo last change"),
			"Last saved change was undone. Your estimated monthly income is now $3900.00, your total monthly expenses are $3090.00, and your monthly savings are $810.00."
		)

		check_equal(
			"journal row count unchanged after undo",
			count_change_journal_entries(),
			1
		)

		updated = current_profile()
		updated["income_streams"].append({
			"name": "Side gig",
			"amount": 500,
			"frequency": "monthly",
		})
		save_profile(updated)

		check_equal(
			"generic income update blocked with multi-income",
			run_deterministic_engine(current_profile(), "set monthly income to 3500"),
			"Multiple income streams detected. No generic income change was applied. Use Edit Profile instead."
		)

		total = passes + len(failures)
		print("")
		print(f"Regression summary: {passes}/{total} passed.")

		if failures:
			print("Failing tests:")
			for name in failures:
				print(f" - {name}")
			return 1

		print("All regression tests passed.")
		return 0

	finally:
		BASE_DIR = original_base_dir
		FINANCE_DIR = original_finance_dir
		REPORTS_DIR = original_reports_dir
		PROFILE_PATH = original_profile_path
		PROFILE_BACKUP_PATH = original_backup_path
		SUMMARY_PATH = original_summary_path
		CHANGE_JOURNAL_PATH = original_change_journal_path

		shutil.rmtree(temp_root, ignore_errors=True)


# -------------------- Main Menu --------------------

def main():
	while True:
		print("\n=== EON PFA ===")
		print("1. Create New Profile")
		print("2. View Profile")
		print("3. Local AI")
		print("4. Edit Profile")
		print("5. Exit")

		choice = input("Select an option: ").strip()

		if choice == "1":
			create_new_profile_action()

		elif choice == "2":
			view_profile()

		elif choice == "3":
			selected = select_local_model_interactive()
			if selected is None:
				continue

			print("Enter your prompt for the Local AI:")
			print("(Paste one or multiple lines. Press Enter on an empty line to submit.)")

			prompt_lines = []

			while True:
				line = input("> " if not prompt_lines else "").replace("\r", "")
				if not line.strip():
					break
				prompt_lines.append(line.strip())

			prompt = " ".join(prompt_lines).strip()

			if not prompt:
				print("❌ Prompt cannot be empty.")
				continue

			ask_local_ai(prompt)

		elif choice == "4":
			edit_profile()

		elif choice == "5":
			print("Bye.")
			break

		else:
			print("❌ Invalid option.")


def print_usage():
	print("EON Personal Financial Assistant")
	print("Usage: python EON_PFA.py [--help] [--version] [--self-test | --regression]")
	print("  --help       Show this help message")
	print("  --version    Show program version")
	print("  --self-test  Run regression tests")
	print("  --regression Alias for --self-test")
	print("")
	print("Environment variables:")
	print("  EON_PFA_BASE_DIR   Override the base AI directory")
	print("  EON_PFA_MODEL_PATH Override the GGUF model path (optional; else discover)")
	print("  K1_MODELS_DIR      Directory scanned for replaceable local GGUF tools")


def entrypoint():
	argv = sys.argv[1:]

	if "--help" in argv or "-h" in argv:
		print_usage()
		return 0

	if "--version" in argv:
		print(f"EON PFA version {PROGRAM_VERSION}")
		return 0

	if "--self-test" in argv or "--regression" in argv:
		return run_regression_tests()

	main()
	return 0


if __name__ == "__main__":
	raise SystemExit(entrypoint())
