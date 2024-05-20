#!/usr/bin/python
# -*- coding: UTF-8 -*-

import json
import os
import re
import time

################

index_filepath = './index.json'
evolution_filepath = './evolutions.json'
form_filepath = './formchanges.json'
raw_folder = './raw'
dest_folder = './dist'

################

class PokemonId:
  def __init__(self, text: str):
    parts = text.split('.')
    self.number = int(parts[0])
    self.form = 0 if len(parts) < 2 else int(parts[1])
  def __eq__(self, other):
    if not(isinstance(other, PokemonId)):
      return False
    return self.number == other.number and self.form == other.form
  def __hash__(self):
    return hash((self.number, self.form))
  def __repr__(self):
    return f'{self.number:04}-{self.form:03}'

class MoveEntry:
  def __init__(self, text: str):
    parts = text.split(':')
    self.index = int(parts[0])
    if len(parts) >= 2:
      self.value = parts[1]
    if len(parts) >= 3:
      self.value2 = parts[2]

class LearnsetEntry:
  def __init__(self, text: str):
    parts = text.rstrip('\n').split('\t')
    self.pokemon = PokemonId(parts[0])
    if len(parts[1]) > 0:
      self.moves = [MoveEntry(x) for x in parts[1].split(',')]
      self.moves = list(filter(lambda entry: entry.index > 0, self.moves))
    else:
      self.moves = []
    self.is_valid = self.pokemon.number > 0 and len(self.moves) > 0

################

def read_learnset_data(learnset_filepath: str):
  with open(learnset_filepath, encoding='UTF-8') as file:
    lines = file.readlines()
  entries = map(LearnsetEntry, lines)
  return entries

def read_availability(availability_file_path: str):
  availability_collection = []
  if os.path.isfile(availability_file_path):
    with open(availability_file_path, encoding='UTF-8') as availability_file:
      for line in availability_file:
        pid = PokemonId(line.rstrip())
        if pid.number > 0:
          availability_collection.append(pid)
  return availability_collection

def find_pre_evolution(pokemon: PokemonId):
  for key, value in evolution_data.items():
    if pokemon in value:
      return key

def find_pre_evolutions(pokemon: PokemonId):
  pre_evolutions = []
  pre_evolution = find_pre_evolution(pokemon)
  if pre_evolution:
    pre_evolutions.append(pre_evolution)
    pre_pre_evolution = find_pre_evolution(pre_evolution)
    if pre_pre_evolution:
      pre_evolutions.append(pre_pre_evolution)
  return pre_evolutions

def create_move_object(method: str, entry: MoveEntry):
  move_object = {
    'move': entry.index,
    'method': method,
  }
  match method:
    case 'basic':
      move_object['method'] = 'levelup'
      move_object['level'] = 1
    case 'levelup':
      level = int(entry.value)
      if (level <= 0): # evolution moves, 0 in sm-la, -3 in sv
        move_object['method'] = 'evolution'
      else:
        move_object['level'] = level
      if (hasattr(entry, 'value2')): # master moves in la
        move_object['master_level'] = int(entry.value2)
    case 'tm' | 'tr':
      if (hasattr(entry, 'value')):
        move_object['item'] = entry.value
    case 'tutor_ult':
      move_object['method'] = 'tutor'
    case 'zmove':
      move_object['original_move'] = entry.value
  return move_object

def merge_learnsets(collection: dict[str, list[LearnsetEntry]]):
  pokemon_keys: list[PokemonId] = []
  for learnset in collection.values():
    for entry in learnset:
      pokemon_keys.append(entry.pokemon)
  pokemon_keys = sorted(set(pokemon_keys), key=lambda x: (x.number, x.form))
  pokemon_collection: dict[PokemonId, list[object]] = {}
  for key in pokemon_keys:
      pokemon_collection[key] = []

  for file_key, learnset in collection.items():
    m = re.match('^(.+?)(?:@(.+?)){0,1}/(.+?)$', file_key)
    game_key = m.group(1)
    version = m.group(2)
    method_key = m.group(3)
    for entry in learnset:
      templist = []
      for move in entry.moves:
        move_object = create_move_object(method_key, move)
        templist.append(move_object)
        if not(move_object['method'] in output_method_keys):
          output_method_keys.append(move_object['method'])
      if game_key == 'scarletviolet' and method_key == 'tm': # remove unused tm and sort
        templist = list(filter(lambda move_object: 'item' in move_object, templist))
        templist.sort(key = lambda move_object: move_object['item'])
      pokemon_collection[entry.pokemon].extend(templist)
  
  return pokemon_collection

def apply_pre_evolutions(collection: dict[PokemonId, list[object]]):
  new_collection: dict[PokemonId, list[object]] = {}
  for pokemon, moves in collection.items():
    new_moves = moves.copy()
    for pre_evolution in find_pre_evolutions(pokemon):
      if not(pre_evolution in collection):
        continue
      for pre_move in collection[pre_evolution]:
        if any(x['move'] == pre_move['move'] for x in moves):
          continue
        new_move = pre_move.copy()
        new_move['pokemon'] = pre_evolution.number
        new_move['form'] = pre_evolution.form
        new_moves.append(new_move)
    new_collection[pokemon] = new_moves
  return new_collection

def apply_form_changes(collection: dict[PokemonId, list[object]]):
  new_collection: dict[PokemonId, list[object]] = {}
  for pokemon, moves in collection.items():
    new_collection[pokemon] = moves.copy()

  for form_line in form_data:
    for target_form in form_line:
      if not(target_form in collection):
        continue
      for other_form in form_line:
        if target_form == other_form:
          continue
        if not(other_form in collection):
          continue
        for form_move in collection[other_form]:
          if form_move['method'] == 'special':
            continue
          if any(x['move'] == form_move['move'] for x in collection[target_form]):
            continue
          new_move = form_move.copy()
          if not('pokemon' in new_move):
            new_move['pokemon'] = other_form.number
            new_move['form'] = other_form.form
          new_collection[target_form].append(new_move)

  return new_collection

################

with open(index_filepath, encoding='UTF-8') as index_file:
  index_data : dict[str, list[str]] = json.load(index_file)

with open(evolution_filepath, encoding='UTF-8') as evolution_file:
  # "025.00" : ["026.00","026.01"],
  data : dict[str, list[str]] = json.load(evolution_file)
  evolution_data : dict[PokemonId, list[PokemonId]] = {}
  for key in data:
    evolution_data[PokemonId(key)] = [PokemonId(x) for x in data[key]]

with open(form_filepath, encoding='UTF-8') as form_file:
  # ["006.00","006.01","006.02"],
  data : list[list[str]] = json.load(form_file)
  form_data = [[PokemonId(y) for y in x] for x in data]

################

input_method_keys : list[str] = []
output_method_keys : list[str] = []

for game_key, filenames in index_data.items():
  start_time = time.time()
  raw_learnset_collection: dict[str, list[LearnsetEntry]] = {}
  availability_collection = read_availability(os.path.join(raw_folder, filenames[0].split('/')[0], 'availabilities.txt'))
  for file_key in filenames:
    filepath = os.path.join(raw_folder, file_key + '.txt')
    method_key : str = file_key.split('/')[1]
    learnset_table = read_learnset_data(filepath)
    learnset_table = list(filter(lambda entry: entry.is_valid, learnset_table))
    if len(availability_collection) > 0:
      learnset_table = list(filter(lambda entry: entry.pokemon in availability_collection, learnset_table))
    raw_learnset_collection[file_key] = learnset_table
    if not(method_key in input_method_keys):
      input_method_keys.append(method_key)
  merged_learnset_collection = merge_learnsets(raw_learnset_collection)
  merged_learnset_collection = apply_pre_evolutions(merged_learnset_collection)
  merged_learnset_collection = apply_form_changes(merged_learnset_collection)
  
  dist_learnset_collection = []
  for pokemon, moves in merged_learnset_collection.items():
    dist_learnset_collection.append({
      'pokemon': pokemon.number,
      'form': pokemon.form,
      'moves': moves,
    })
  
  dist_text = json.dumps(dist_learnset_collection, indent=2)
  dist_filepath = os.path.join(dest_folder, game_key + '.json')
  if not os.path.exists(dest_folder):
    os.makedirs(dest_folder)
  with open(dist_filepath, 'w') as file:
    file.write(dist_text)

  end_time = time.time()
  elapsed_time = end_time - start_time
  entry_count = len(dist_learnset_collection)
  pokemon_numbers = list(map(lambda x: x['pokemon'], dist_learnset_collection))
  pokemon_count = len(set(pokemon_numbers))
  pokemon_max = max(pokemon_numbers)
  print(f'::group::Generated "{dist_filepath}": {pokemon_count}/{pokemon_max} pokemon, {entry_count} entries, {elapsed_time * 1000:.0f}ms.')
  for file_key in filenames:
    filepath = os.path.join(raw_folder, file_key + '.txt')
    print(f' {filepath}')
  print('::endgroup::')
