#!/usr/bin/env python3
import copy
# ‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹
#  SPDX-License-Identifier: GPL-2.0
#  Copyright (c) 2023 Ricardo Pardini <ricardo@pardini.net>
#  This file is a part of the Armbian Build Framework https://github.com/armbian/build/
# ‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹‹
import json
import logging
import os

import sys
import yaml

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import armbian_utils

# Prepare logging
armbian_utils.setup_logging()
log: logging.Logger = logging.getLogger("targets-compositor")

# if targets.yaml is not present, process the board inventory:
# - if userpatched boards present, only include those, in all branches. use a fixed RELEASE.
# - if no userpatched boards present, include all core boards, in all branches. use a fixed RELEASE.

# if targets.yaml is present, process it. load the templates, the items in each, and produce a list of invocations to build.

# get the first argv, which is the board inventory file.
board_inventory_file = sys.argv[1]
# read it as json, modern way
with open(board_inventory_file, 'r') as f:
	board_inventory = json.load(f)

# Lets resolve the all-boards-all-branches list
all_boards_all_branches = []
boards_by_support_level_and_branches = {}
not_eos_boards_all_branches = []
not_eos_with_video_boards_all_branches = []

for board in board_inventory:
	for branch in board_inventory[board]["BOARD_POSSIBLE_BRANCHES"]:
		data_from_inventory = {"BOARD": board, "BRANCH": branch}
		all_boards_all_branches.append(data_from_inventory)

		if board_inventory[board]["BOARD_SUPPORT_LEVEL"] not in boards_by_support_level_and_branches:
			boards_by_support_level_and_branches[board_inventory[board]["BOARD_SUPPORT_LEVEL"]] = []
		boards_by_support_level_and_branches[board_inventory[board]["BOARD_SUPPORT_LEVEL"]].append(data_from_inventory)

		if board_inventory[board]["BOARD_SUPPORT_LEVEL"] != "eos":
			not_eos_boards_all_branches.append(data_from_inventory)
			if board_inventory[board]["BOARD_HAS_VIDEO"]:
				not_eos_with_video_boards_all_branches.append(data_from_inventory)

# get the third argv, which is the targets.yaml file.
targets_yaml_file = sys.argv[3]
# read it as yaml, modern way
with open(targets_yaml_file, 'r') as f:
	targets = yaml.load(f, Loader=yaml.FullLoader)

# Keep a running of all the invocations we want to make.
invocations_dict: list[dict] = []

# Loop over targets
for target_name in targets["targets"]:
	target_obj = targets["targets"][target_name]

	if "enabled" in target_obj and not target_obj["enabled"]:
		log.warning(f"Skipping disabled target '{target_name}'...")
		continue

	all_items = []
	all_expansions = []

	if "expand" in target_obj:
		for one_expand_name in target_obj["expand"]:
			one_expand = target_obj["expand"][one_expand_name]
			one_expansion = {"vars": {}, "configs": (target_obj["configs"] if "configs" in target_obj else []),
							 "pipeline": (target_obj["pipeline"] if "pipeline" in target_obj else {})}
			one_expansion["vars"].update(target_obj["vars"])
			one_expansion["vars"].update(one_expand)
			all_expansions.append(one_expansion)
	else:  # single expansion with the vars
		one_expansion = {"vars": {}, "configs": (target_obj["configs"] if "configs" in target_obj else []),
						 "pipeline": (target_obj["pipeline"] if "pipeline" in target_obj else {})}
		one_expansion["vars"].update(target_obj["vars"])
		all_expansions.append(one_expansion)

	# loop over the items, which can themselves be lists
	if "items" in target_obj:
		for item in target_obj["items"]:
			if isinstance(item, list):
				for item_item in item:
					all_items.append(item_item)
			else:
				all_items.append(item)

	# Now add to all_items by resolving the "items-from-inventory" key
	if "items-from-inventory" in target_obj:
		# loop over the keys
		for key in target_obj["items-from-inventory"]:
			to_add = []
			if key == "all":
				to_add.extend(all_boards_all_branches)
			elif key == "not-eos":
				to_add.extend(not_eos_boards_all_branches)
			elif key == "not-eos-with-video":
				to_add.extend(not_eos_with_video_boards_all_branches)
			else:
				to_add.extend(boards_by_support_level_and_branches[key])
			log.info(f"Adding '{key}' from inventory to target '{target_name}': {len(to_add)} targets")
			all_items.extend(to_add)

	for one_expansion in all_expansions:
		# loop over the items
		for item in all_items:
			one_invocation_vars = {}
			one_invocation_vars.update(one_expansion["vars"])
			one_invocation_vars.update(item)
			# Special case for BETA, read this from TARGETS_BETA environment and force it.
			one_invocation_vars.update({"BETA": os.environ.get("TARGETS_BETA", "")})
			expanded = {"vars": one_invocation_vars, "configs": one_expansion["configs"], "pipeline": one_expansion["pipeline"]}
			invocations_dict.append(expanded)

# de-duplicate invocations_dict
invocations_unique = {}
for invocation in invocations_dict:
	invocation_key = json.dumps(invocation, sort_keys=True)  # this sorts the keys, so that the order of the keys doesn't matter. also, heavy.
	invocations_unique[invocation_key] = invocation

log.info(
	f"Generated {len(invocations_dict)} invocations from {len(targets['targets'])} target groups, de-duped to {len(invocations_unique)} invocations.")

if len(invocations_dict) != len(invocations_unique):
	log.warning(f"Duplicate invocations found, de-duped from {len(invocations_dict)} to {len(invocations_unique)}")

# A plain list
all_invocations = list(invocations_unique.values())

# Add information from inventory to each invocation, so it trickles down the pipeline.
for invocation in all_invocations:
	if invocation["vars"]["BOARD"] not in board_inventory:
		log.error(f"Board '{invocation['vars']['BOARD']}' not found in inventory!")
		sys.exit(3)
	invocation["inventory"] = copy.deepcopy(board_inventory[invocation["vars"]["BOARD"]])  # deep copy, so we can modify it
	# Add "virtual" BOARD_SLASH_BRANCH var, for easy filtering
	invocation["inventory"]["BOARD_TOP_LEVEL_VARS"]['BOARD_SLASH_BRANCH'] = f"{invocation['vars']['BOARD']}/{invocation['vars']['BRANCH']}"

# Allow filtering of invocations, using environment variable:
# - TARGETS_FILTER_INCLUDE: only include invocations that match this query-string
# For example: TARGETS_FILTER_INCLUDE="BOARD:xxx,BOARD:yyy"
include_filter = os.environ.get("TARGETS_FILTER_INCLUDE", "").strip()
if include_filter:
	log.info(f"Filtering {len(all_invocations)} invocations to only include those matching: '{include_filter}'")
	include_filter_list: list[dict[str, str]] = []
	include_raw_split = include_filter.split(",")
	for include_raw in include_raw_split:
		include_split = include_raw.split(":")
		if len(include_split) != 2:
			log.error(f"Invalid include filter, wrong format: '{include_raw}'")
			sys.exit(1)
		if include_split[0].strip() == "" or include_split[1].strip() == "":
			log.error(f"Invalid include filter, either key or value empty: '{include_raw}'")
			sys.exit(1)
		include_filter_list.append({"key": include_split[0].strip(), "value": include_split[1].strip()})

	invocations_filtered = []
	for invocation in all_invocations:
		for include_filter in include_filter_list:
			top_level_vars = invocation["inventory"]["BOARD_TOP_LEVEL_VARS"]
			if include_filter["key"] not in top_level_vars:
				log.warning(
					f"Problem with include filter, key '{include_filter['key']}' not found in inventory data for board '{invocation['vars']['BOARD']}'")
				continue
			filtered_key = top_level_vars[include_filter["key"]]
			# If it is an array...
			if isinstance(filtered_key, list):
				if include_filter["value"] in filtered_key:
					invocations_filtered.append(invocation)
					break
			else:
				if filtered_key == include_filter["value"]:
					invocations_filtered.append(invocation)
					break

	log.info(f"Filtered invocations to {len(invocations_filtered)} invocations after include filters.")
	if len(invocations_filtered) == 0:
		log.error(f"No invocations left after filtering '{include_filter}'!")
		sys.exit(2)

	all_invocations = invocations_filtered
else:
	log.info("No include filter set, not filtering invocations.")

counter = 1
for one_invocation in all_invocations:
	# target_id is the counter left-padded with zeros to 10 digits, plus the total number of invocations, left-padded with zeros to 10 digits.
	one_invocation["target_id"] = f"{counter:010d}" + f"{len(all_invocations):010d}"
	counter += 1

# dump invocation list as json
invocations_json = json.dumps(all_invocations, indent=4, sort_keys=True)
print(invocations_json)

# enough
sys.exit(0)
