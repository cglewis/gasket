import inspect
import json
import os


CFG_PATH = os.path.dirname(os.path.abspath(
    inspect.getfile(inspect.currentframe())))


class LoadRyuTables(object):

    def __init__(self, cfgpath):
        self.cfgpath = cfgpath
        self._ofproto_parser = None
        self._class_name_to_name_ids = {
            'OFPTableFeaturePropInstructions': 'instruction_ids',
            'OFPTableFeaturePropNextTables': 'table_ids',
            'OFPTableFeaturePropActions': 'action_ids',
            'OFPTableFeaturePropOxm': 'oxm_ids'}
        self.ryu_table_translator = OpenflowToRyuTranslator(self.cfgpath)
        self.ryu_tables = []
        self.tables = None

    def _read_json_document(self, filename):
        python_object_result = None
        try:
            self.ryu_table_translator.set_json_document(filename)
            self.ryu_table_translator.create_ryu_structure()
            python_object_result = self.ryu_table_translator.tables
        except (ValueError, IOError) as e:
            print(e)
        return python_object_result

    def load_tables(self, filename, ofproto_parser):
        self.ryu_tables = []
        self._ofproto_parser = ofproto_parser
        self.tables = self._read_json_document(
            os.path.join(self.cfgpath, filename))
        if self.tables is None:
            return
        self.ryu_tables = self._create_tables(self.tables)

    def _create_tables(self, tables_information):
        table_array = []
        for table in tables_information:
            for k, v in list(table.items()):
                table_class = getattr(self._ofproto_parser, k)
                properties = self._create_features(v['properties'])
                v['properties'] = properties
                v['name'] = v['name'].encode('utf-8')
                new_table = table_class(**v)
                table_array.append(new_table)
        return table_array

    def _create_features(self, table_features_information):
        features_array = []
        for feature in table_features_information:
            for k, v in list(feature.items()):
                name_id = self._class_name_to_name_ids[k]
                feature_class = getattr(self._ofproto_parser, k)
                instruction_ids = self._create_instructions(v[name_id])
                v[name_id] = instruction_ids
                v['type_'] = v.pop('type')
                new_feature = feature_class(**v)
                features_array.append(new_feature)
        return features_array

    def _create_instructions(self, instruction_ids_information):
        instruction_array = []
        for instruction in instruction_ids_information:
            if isinstance(instruction, dict):
                for k, v in list(instruction.items()):
                    instruction_class = getattr(self._ofproto_parser, k)
                    v['type_'] = v.pop('type')
                    new_instruction = instruction_class(**v)
                    instruction_array.append(new_instruction)
            else:
                instruction_array = instruction_ids_information
                break
        return instruction_array


# This script allows dynamically create a set of tables. Each table has
# a set of properties that allows take some actions depended of the
# incoming package. Those properties are defined in the file
# 'openflow_structure_tables.json', which are based on the openflow protocol
# version 1.3. Also, the fields allowed in each property are written in this
# file, each of those fields are accepted by the switch 5400.
# The output of this script is an json file with the tables well structure.
# This structure is converted from openflow structure to ryu structure using
# the file 'ofproto_to_ryu.json', so the json file generated will be to the
# SDN ryu framework. But, if is necessary convert the structure to another
# SDN framework, you will only have to change the file ofproto_to_ryu.
class OpenflowToRyuTranslator(object):

    def __init__(self, cfgpath):
        self.cfgpath = cfgpath
        self.custom_json = CustomJson()
        # file with the variables in openflow to map them into Ryu variables
        self.openflow_to_ryu = self.custom_json.read_json_document(
            os.path.join(self.cfgpath, 'ofproto_to_ryu.json'))
        # variable used to save the ryu structure tables
        self.tables = []
        self.document_with_openflow_tables = None

    def set_json_document(self, filepath):
        self.document_with_openflow_tables = self.custom_json.read_json_document(
            filepath)

    # The following functions are used to create the final structure
    # (same structure that use ryu library)
    def create_ryu_structure(self):
        table_properties = []
        self.tables = []
        for openflow_table in self.document_with_openflow_tables:
            table_properties = []
            for property_item in openflow_table['properties']:
                fields_tag = self.openflow_to_ryu['tables'][property_item['name']]['action_tag']
                actions_ids = property_item[fields_tag]
                table_properties.append(
                    self.create_table_feature(
                        property_item['name'],
                        actions_ids,
                        property_item['type']))

            self.tables.append(
                self.create_table(
                    table_id=openflow_table['table_id'],
                    name=openflow_table['name'],
                    config=3,
                    max_entries=openflow_table['max_entries'],
                    metadata_match=0,
                    metadata_write=0,
                    properties=table_properties))

    def create_table(self, table_id, name, config, max_entries,
                     metadata_match, metadata_write, properties):
        return {
            self.openflow_to_ryu['table_tag']: {
                'config': config,
                'max_entries': max_entries,
                'metadata_match': metadata_match,
                'metadata_write': metadata_write,
                'name': name,
                'properties': properties,
                'table_id': table_id}}

    def create_table_feature(self, name, actions, type_id):
        table_feature_name = self.openflow_to_ryu['tables'][name]['name']
        instruction_id_name = self.openflow_to_ryu['tables'][name]['action_tag']
        action_id_name = self.openflow_to_ryu['content'][instruction_id_name]

        if action_id_name:
            new_array_instructions = []
            for action in actions:
                if 'name' in action:
                    action.pop('name')
                new_array_instructions.append({action_id_name: action})
        else:
            new_array_instructions = actions

        new_table_feature = {
            table_feature_name: {
                instruction_id_name: new_array_instructions,
                'type': type_id}}

        return new_table_feature


class CustomJson(object):

    def read_json_document(self, filename):
        return json.load(open(filename))
