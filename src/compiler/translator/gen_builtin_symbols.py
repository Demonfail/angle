#!/usr/bin/python
# Copyright 2018 The ANGLE Project Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# gen_builtin_symbols.py:
#  Code generation for the built-in symbol tables.

from collections import OrderedDict
from datetime import date
import argparse
import json
import re
import os

def set_working_dir():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

set_working_dir()

parser = argparse.ArgumentParser()
parser.add_argument('--dump-intermediate-json', help='Dump parsed function data as a JSON file builtin_functions.json', action="store_true")
args = parser.parse_args()

template_immutablestringtest_cpp = """// GENERATED FILE - DO NOT EDIT.
// Generated by {script_name} using data from {function_data_source_name}.
//
// Copyright {copyright_year} The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// ImmutableString_test_autogen.cpp:
//   Tests for matching script-generated hashes with runtime computed hashes.

#include "compiler/translator/ImmutableString.h"
#include "gtest/gtest.h"

namespace sh
{{

TEST(ImmutableStringTest, ScriptGeneratedHashesMatch)
{{
{script_generated_hash_tests}
}}

}}  // namespace sh
"""

# By having the variables defined in a cpp file we ensure that there's just one instance of each of the declared variables.
template_symboltable_cpp = """// GENERATED FILE - DO NOT EDIT.
// Generated by {script_name} using data from {function_data_source_name}.
//
// Copyright {copyright_year} The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// SymbolTable_autogen.cpp:
//   Compile-time initialized built-ins.

#include "compiler/translator/SymbolTable.h"

#include "angle_gl.h"
#include "compiler/translator/ImmutableString.h"
#include "compiler/translator/StaticType.h"
#include "compiler/translator/Symbol.h"
#include "compiler/translator/SymbolUniqueId.h"
#include "compiler/translator/SymbolTable.h"

namespace sh
{{

// This is a class instead of a namespace so that we can restrict access to TSymbolUniqueId
// constructor taking an integer to here.
class BuiltInId
{{
  public:

{builtin_id_declarations}

}};

const int TSymbolTable::kLastStaticBuiltInId = {last_static_builtin_id};

namespace BuiltInName
{{

{name_declarations}

}}  // namespace BuiltInName

namespace BuiltInParameters
{{

{parameter_declarations}

}}  // namespace BuiltInParameters

namespace UnmangledBuiltIns
{{

{unmangled_builtin_declarations}

}}  // namespace UnmangledBuiltIns

// TODO(oetuaho): Would be nice to make this a class instead of a namespace so that we could friend
// this from TFunction. Now symbol constructors taking an id have to be public even though they're
// not supposed to be accessible from outside of here. http://anglebug.com/2390
namespace BuiltInFunction
{{

{function_declarations}

}}  // namespace BuiltInFunction

void TSymbolTable::insertBuiltInFunctions(sh::GLenum shaderType)
{{
{insert_functions}
}}

const UnmangledBuiltIn *TSymbolTable::getUnmangledBuiltInForShaderVersion(const ImmutableString &name, int shaderVersion)
{{
    uint32_t nameHash = name.hash32();
{get_unmangled_builtin}
}}

}}  // namespace sh
"""

functions_txt_filename = 'builtin_function_declarations.txt'

basic_mangled_names = {
    'Float': 'f',
    'Int': 'i',
    'UInt': 'u',
    'Bool': 'b',
    'YuvCscStandardEXT': 'y',
    'Sampler2D': 's2',
    'Sampler3D': 's3',
    'SamplerCube': 'sC',
    'Sampler2DArray': 'sA',
    'SamplerExternalOES': 'sX',
    'SamplerExternal2DY2YEXT': 'sY',
    'Sampler2DRect': 'sR',
    'Sampler2DMS': 'sM',
    'ISampler2D': 'is2',
    'ISampler3D': 'is3',
    'ISamplerCube': 'isC',
    'ISampler2DArray': 'isA',
    'ISampler2DMS': 'isM',
    'USampler2D': 'us2',
    'USampler3D': 'us3',
    'USamplerCube': 'usC',
    'USampler2DArray': 'usA',
    'USampler2DMS': 'usM',
    'Sampler2DShadow': 's2s',
    'SamplerCubeShadow': 'sCs',
    'Sampler2DArrayShadow': 'sAs',
    'Image2D': 'I2',
    'IImage2D': 'iI2',
    'UImage2D': 'uI2',
    'Image3D': 'I3',
    'IImage3D': 'iI3',
    'UImage3D': 'uI3',
    'Image2DArray': 'IA',
    'IImage2DArray': 'iIA',
    'UImage2DArray': 'uIA',
    'ImageCube': 'Ic',
    'IImageCube': 'iIc',
    'UImageCube': 'uIc',
    'AtomicCounter': 'a'
}

levels = ['ESSL3_1_BUILTINS', 'ESSL3_BUILTINS', 'ESSL1_BUILTINS', 'COMMON_BUILTINS']

class GroupedList:
    """"Class for storing a list of objects grouped by symbol table level and condition."""
    def __init__(self):
        self.objs = OrderedDict()
        # We need to add all the levels here instead of lazily since they must be in a specific order.
        for l in levels:
            self.objs[l] = OrderedDict()

    def add_obj(self, level, condition, name, obj):
        if (level not in levels):
            raise Exception('Unexpected level: ' + str(level))
        if condition not in self.objs[level]:
            self.objs[level][condition] = OrderedDict()
        self.objs[level][condition][name] = obj

    def has_key(self, level, condition, name):
        if (level not in levels):
            raise Exception('Unexpected level: ' + str(level))
        if condition not in self.objs[level]:
            return False
        return (name in self.objs[level][condition])

    def get(self, level, condition, name):
        if self.has_key(level, condition, name):
            return self.objs[level][condition][name]
        return None

    def iter_conditions(self, level):
        return self.objs[level].iteritems()


class TType:
    def __init__(self, glsl_header_type):
        if isinstance(glsl_header_type, basestring):
            self.data = self.parse_type(glsl_header_type)
        else:
            self.data = glsl_header_type
        self.normalize()

    def normalize(self):
        # Note that this will set primarySize and secondarySize also on genTypes. In that case they
        # are overridden when the specific types are generated.
        if 'primarySize' not in self.data:
            if ('secondarySize' in self.data):
                raise Exception('Unexpected secondarySize on type that does not have primarySize set')
            self.data['primarySize'] = 1
        if 'secondarySize' not in self.data:
            self.data['secondarySize'] = 1
        if 'precision' not in self.data:
            self.data['precision'] = 'Undefined'
        if 'qualifier' not in self.data:
            self.data['qualifier'] = 'Global'

    def get_statictype_string(self):
        template_type = 'StaticType::Get<Ebt{basic}, Ebp{precision}, Evq{qualifier}, {primarySize}, {secondarySize}>()'
        return template_type.format(**self.data)

    def get_mangled_name(self, separator = ';'):
        mangled_name = ''

        if self.is_matrix():
            mangled_name += str(self.data['primarySize'])
            mangled_name += str(self.data['secondarySize'])
        elif self.data['primarySize'] > 1:
            mangled_name += str(self.data['primarySize'])

        mangled_name += basic_mangled_names[self.data['basic']]

        mangled_name += separator
        return mangled_name

    def is_vector(self):
        return self.data['primarySize'] > 1 and self.data['secondarySize'] == 1

    def is_matrix(self):
        return self.data['secondarySize'] > 1

    def specific_sampler_or_image_type(self, basic_type_prefix):
        if 'genType' in self.data:
            type = {}
            if 'basic' not in self.data:
                type['basic'] = {'': 'Float', 'I': 'Int', 'U': 'UInt'}[basic_type_prefix]
                type['primarySize'] = self.data['primarySize']
            else:
                type['basic'] = basic_type_prefix + self.data['basic']
                type['primarySize'] = 1
            type['precision'] = 'Undefined'
            return TType(type)
        return self

    def specific_type(self, vec_size):
        type = {}
        if 'genType' in self.data:
            type['basic'] = self.data['basic']
            type['precision'] = self.data['precision']
            type['qualifier'] = self.data['qualifier']
            type['primarySize'] = vec_size
            type['secondarySize'] = 1
            return TType(type)
        return self

    def parse_type(self, glsl_header_type):
        if glsl_header_type.startswith('out '):
            type_obj = self.parse_type(glsl_header_type[4:])
            type_obj['qualifier'] = 'Out'
            return type_obj
        if glsl_header_type.startswith('inout '):
            type_obj = self.parse_type(glsl_header_type[6:])
            type_obj['qualifier'] = 'InOut'
            return type_obj

        basic_type_map = {
            'float': 'Float',
            'int': 'Int',
            'uint': 'UInt',
            'bool': 'Bool',
            'void': 'Void',
            'atomic_uint': 'AtomicCounter',
            'yuvCscStandardEXT': 'YuvCscStandardEXT'
        }

        if glsl_header_type in basic_type_map:
            return {'basic': basic_type_map[glsl_header_type]}

        type_obj = {}

        basic_type_prefix_map = {'': 'Float', 'i': 'Int', 'u': 'UInt', 'b': 'Bool', 'v': 'Void'}

        vec_re = re.compile(r'^([iub]?)vec([234]?)$')
        vec_match = vec_re.match(glsl_header_type)
        if vec_match:
            type_obj['basic'] = basic_type_prefix_map[vec_match.group(1)]
            if vec_match.group(2) == '':
                # Type like "ivec" that represents either ivec2, ivec3 or ivec4
                type_obj['genType'] = 'vec'
            else:
                # vec with specific size
                type_obj['primarySize'] = int(vec_match.group(2))
            return type_obj

        mat_re = re.compile(r'^mat([234])(x([234]))?$')
        mat_match = mat_re.match(glsl_header_type)
        if mat_match:
            type_obj['basic'] = 'Float'
            if len(glsl_header_type) == 4:
                mat_size = int(mat_match.group(1))
                type_obj['primarySize'] = mat_size
                type_obj['secondarySize'] = mat_size
            else:
                type_obj['primarySize'] = int(mat_match.group(1))
                type_obj['secondarySize'] = int(mat_match.group(3))
            return type_obj

        gen_re = re.compile(r'^gen([IUB]?)Type$')
        gen_match = gen_re.match(glsl_header_type)
        if gen_match:
            type_obj['basic'] = basic_type_prefix_map[gen_match.group(1).lower()]
            type_obj['genType'] = 'yes'
            return type_obj

        if glsl_header_type.startswith('sampler'):
            type_obj['basic'] = glsl_header_type[0].upper() + glsl_header_type[1:]
            return type_obj

        if glsl_header_type.startswith('gsampler') or glsl_header_type.startswith('gimage'):
            type_obj['basic'] = glsl_header_type[1].upper() + glsl_header_type[2:]
            type_obj['genType'] = 'sampler_or_image'
            return type_obj

        if glsl_header_type == 'gvec4':
            return {'primarySize': 4, 'genType': 'sampler_or_image'}
        if glsl_header_type == 'gvec3':
            return {'primarySize': 3, 'genType': 'sampler_or_image'}

        raise Exception('Unrecognized type: ' + str(glsl_header_type))

def get_parsed_functions():

    def parse_function_parameters(parameters):
        if parameters == '':
            return []
        parametersOut = []
        parameters = parameters.split(', ')
        for parameter in parameters:
            parametersOut.append(TType(parameter.strip()))
        return parametersOut

    lines = []
    with open(functions_txt_filename) as f:
        lines = f.readlines()
    lines = [line.strip() for line in lines if line.strip() != '' and not line.strip().startswith('//')]

    fun_re = re.compile(r'^(\w+) (\w+)\((.*)\);$')

    parsed_functions = OrderedDict()
    group_stack = []
    default_metadata = {}

    for line in lines:
        fun_match = fun_re.match(line)
        if line.startswith('GROUP BEGIN '):
            group_rest = line[12:].strip()
            group_parts = group_rest.split(' ', 1)
            current_group = {
                'functions': [],
                'name': group_parts[0],
                'subgroups': {}
            }
            if len(group_parts) > 1:
                group_metadata = json.loads(group_parts[1])
                current_group.update(group_metadata)
            group_stack.append(current_group)
        elif line.startswith('GROUP END '):
            group_end_name = line[10:].strip()
            current_group = group_stack[-1]
            if current_group['name'] != group_end_name:
                raise Exception('GROUP END: Unexpected function group name "' + group_end_name + '" was expecting "' + current_group['name'] + '"')
            group_stack.pop()
            is_top_level_group = (len(group_stack) == 0)
            if is_top_level_group:
                parsed_functions[current_group['name']] = current_group
                default_metadata = {}
            else:
                super_group = group_stack[-1]
                super_group['subgroups'][current_group['name']] = current_group
        elif line.startswith('DEFAULT METADATA'):
            line_rest = line[16:].strip()
            default_metadata = json.loads(line_rest)
        elif fun_match:
            return_type = fun_match.group(1)
            name = fun_match.group(2)
            parameters = fun_match.group(3)
            function_props = {
                'name': name,
                'returnType': TType(return_type),
                'parameters': parse_function_parameters(parameters)
            }
            function_props.update(default_metadata)
            group_stack[-1]['functions'].append(function_props)
        else:
            raise Exception('Unexpected function input line: ' + line)

    return parsed_functions

parsed_functions = get_parsed_functions()

if args.dump_intermediate_json:
    with open('builtin_functions.json', 'w') as outfile:
        def serialize_obj(obj):
            if isinstance(obj, TType):
                return obj.data
            else:
                raise "Cannot serialize to JSON: " + str(obj)
        json.dump(parsed_functions, outfile, indent=4, separators=(',', ': '), default=serialize_obj)

# Declarations of symbol unique ids
builtin_id_declarations = []

# Declarations of name string variables
name_declarations = set()

# Declarations of parameter arrays for builtin TFunctions
parameter_declarations = set()

# Declarations of builtin TFunctions
function_declarations = []

# Code for inserting builtin TFunctions to the symbol table. Grouped by condition.
insert_functions_by_condition = OrderedDict()

# Declarations of UnmangledBuiltIn objects
unmangled_builtin_declarations = set()

# Code for querying builtin function unmangled names.
unmangled_function_if_statements = GroupedList()

# Code for testing that script-generated hashes match with runtime computed hashes.
script_generated_hash_tests = OrderedDict()

id_counter = 0

def hash32(str):
    fnvOffsetBasis = 0x811c9dc5
    fnvPrime = 16777619
    hash = fnvOffsetBasis
    for c in str:
        hash = hash ^ ord(c)
        hash = hash * fnvPrime & 0xffffffff
    sanity_check = '    ASSERT_EQ(0x{hash}u, ImmutableString("{str}").hash32());'.format(hash = ('%x' % hash), str = str)
    script_generated_hash_tests.update({sanity_check: None})
    return hash

def get_suffix(props):
    if 'suffix' in props:
        return props['suffix']
    return ''

def get_extension(props):
    if 'extension' in props:
        return props['extension']
    return 'UNDEFINED'

def get_op(name, function_props):
    if 'op' not in function_props:
        raise Exception('function op not defined')
    if function_props['op'] == 'auto':
        return name[0].upper() + name[1:]
    return function_props['op']

def get_known_to_not_have_side_effects(function_props):
    if 'op' in function_props and function_props['op'] != 'CallBuiltInFunction':
        if 'hasSideEffects' in function_props:
            return 'false'
        else:
            for param in get_parameters(function_props):
                if 'qualifier' in param.data and (param.data['qualifier'] == 'Out' or param.data['qualifier'] == 'InOut'):
                    return 'false'
            return 'true'
    return 'false'

def get_parameters(function_props):
    if 'parameters' in function_props:
        return function_props['parameters']
    return []

def get_function_mangled_name(function_name, parameters):
    mangled_name = function_name + '('
    for param in parameters:
        mangled_name += param.get_mangled_name()
    return mangled_name

def get_unique_identifier_name(function_name, parameters):
    unique_name = function_name + '_'
    for param in parameters:
        unique_name += param.get_mangled_name('_')
    return unique_name

def get_variable_name_to_store_parameters(parameters):
    if len(parameters) == 0:
        return 'empty'
    unique_name = 'p_'
    for param in parameters:
        if 'qualifier' in param.data:
            if param.data['qualifier'] == 'Out':
                unique_name += 'o_'
            if param.data['qualifier'] == 'InOut':
                unique_name += 'io_'
        unique_name += param.get_mangled_name('_')
    return unique_name

def gen_function_variants(function_name, function_props):
    function_variants = []
    parameters = get_parameters(function_props)
    function_is_gen_type = False
    gen_type = set()
    for param in parameters:
        if 'genType' in param.data:
            if param.data['genType'] not in ['sampler_or_image', 'vec', 'yes']:
                raise Exception('Unexpected value of genType "' + str(param.data['genType']) + '" should be "sampler_or_image", "vec", or "yes"')
            gen_type.add(param.data['genType'])
            if len(gen_type) > 1:
                raise Exception('Unexpected multiple values of genType set on the same function: ' + str(list(gen_type)))
    if len(gen_type) == 0:
        function_variants.append(function_props)
        return function_variants

    # If we have a gsampler_or_image then we're generating variants for float, int and uint
    # samplers.
    if 'sampler_or_image' in gen_type:
        types = ['', 'I', 'U']
        for type in types:
            variant_props = function_props.copy()
            variant_parameters = []
            for param in parameters:
                variant_parameters.append(param.specific_sampler_or_image_type(type))
            variant_props['parameters'] = variant_parameters
            variant_props['returnType'] = function_props['returnType'].specific_sampler_or_image_type(type)
            function_variants.append(variant_props)
        return function_variants

    # If we have a normal gentype then we're generating variants for different sizes of vectors.
    sizes = range(1, 5)
    if 'vec' in gen_type:
        sizes = range(2, 5)
    for size in sizes:
        variant_props = function_props.copy()
        variant_parameters = []
        for param in parameters:
            variant_parameters.append(param.specific_type(size))
        variant_props['parameters'] = variant_parameters
        variant_props['returnType'] = function_props['returnType'].specific_type(size)
        function_variants.append(variant_props)
    return function_variants

defined_function_variants = set()

def process_single_function_group(condition, group_name, group):
    global id_counter
    if 'functions' not in group:
        return

    for function_props in group['functions']:
        function_name = function_props['name']
        level = function_props['level']
        extension = get_extension(function_props)
        template_args = {
            'name': function_name,
            'name_with_suffix': function_name + get_suffix(function_props),
            'level': level,
            'extension': extension,
            'op': get_op(function_name, function_props),
            'known_to_not_have_side_effects': get_known_to_not_have_side_effects(function_props)
        }

        function_variants = gen_function_variants(function_name, function_props)

        template_name_declaration = 'constexpr const ImmutableString {name_with_suffix}("{name}");'
        name_declaration = template_name_declaration.format(**template_args)
        if not name_declaration in name_declarations:
            name_declarations.add(name_declaration)

        template_unmangled_if = """if (name == BuiltInName::{name_with_suffix})
{{
    return &UnmangledBuiltIns::{extension};
}}"""
        unmangled_if = template_unmangled_if.format(**template_args)
        unmangled_builtin_no_condition = unmangled_function_if_statements.get(level, 'NO_CONDITION', function_name)
        if unmangled_builtin_no_condition != None and unmangled_builtin_no_condition['extension'] == 'UNDEFINED':
            # We already have this unmangled name without a condition nor extension on the same level. No need to add a duplicate with a condition.
            pass
        elif (not unmangled_function_if_statements.has_key(level, condition, function_name)) or extension == 'UNDEFINED':
            # We don't have this unmangled builtin recorded yet or we might replace an unmangled builtin from an extension with one from core.
            unmangled_function_if_statements.add_obj(level, condition, function_name, {'code': unmangled_if, 'extension': extension})
            unmangled_builtin_declarations.add('constexpr const UnmangledBuiltIn {extension}(TExtension::{extension});'.format(**template_args))

        for function_props in function_variants:
            template_args['id'] = id_counter

            parameters = get_parameters(function_props)

            template_args['unique_name'] = get_unique_identifier_name(template_args['name_with_suffix'], parameters)

            if template_args['unique_name'] in defined_function_variants:
                continue
            defined_function_variants.add(template_args['unique_name'])

            template_args['param_count'] = len(parameters)
            template_args['return_type'] = function_props['returnType'].get_statictype_string()
            template_args['mangled_name'] = get_function_mangled_name(function_name, parameters)

            template_builtin_id_declaration = '    static constexpr const TSymbolUniqueId {unique_name} = TSymbolUniqueId({id});'
            builtin_id_declarations.append(template_builtin_id_declaration.format(**template_args))

            template_mangled_name_declaration = 'constexpr const ImmutableString {unique_name}("{mangled_name}");'
            name_declarations.add(template_mangled_name_declaration.format(**template_args))

            parameters_list = []
            for param in parameters:
                template_parameter = 'TConstParameter({param_type})'
                parameters_list.append(template_parameter.format(param_type = param.get_statictype_string()))
            template_args['parameters_var_name'] = get_variable_name_to_store_parameters(parameters)
            if len(parameters) > 0:
                template_args['parameters_list'] = ', '.join(parameters_list)
                template_parameter_list_declaration = 'constexpr const TConstParameter {parameters_var_name}[{param_count}] = {{ {parameters_list} }};'
                parameter_declarations.add(template_parameter_list_declaration.format(**template_args))
            else:
                template_parameter_list_declaration = 'constexpr const TConstParameter *{parameters_var_name} = nullptr;'
                parameter_declarations.add(template_parameter_list_declaration.format(**template_args))

            template_function_declaration = 'constexpr const TFunction kFunction_{unique_name}(BuiltInId::{unique_name}, BuiltInName::{name_with_suffix}, TExtension::{extension}, BuiltInParameters::{parameters_var_name}, {param_count}, {return_type}, BuiltInName::{unique_name}, EOp{op}, {known_to_not_have_side_effects});'
            function_declarations.append(template_function_declaration.format(**template_args))

            template_insert_function = '    insertBuiltIn({level}, &BuiltInFunction::kFunction_{unique_name});'
            insert_functions_by_condition[condition].append(template_insert_function.format(**template_args))

            id_counter += 1

def process_function_group(group_name, group):
    condition = 'NO_CONDITION'
    if 'condition' in group:
        condition = group['condition']
    if condition not in insert_functions_by_condition:
        insert_functions_by_condition[condition] = []

    process_single_function_group(condition, group_name, group)

    if 'subgroups' in group:
        for subgroup_name, subgroup in group['subgroups'].iteritems():
            process_function_group(subgroup_name, subgroup)

for group_name, group in parsed_functions.iteritems():
    process_function_group(group_name, group)

output_strings = {
    'script_name': os.path.basename(__file__),
    'copyright_year': date.today().year,

    'builtin_id_declarations': '\n'.join(builtin_id_declarations),
    'last_static_builtin_id': id_counter - 1,
    'name_declarations': '\n'.join(sorted(list(name_declarations))),

    'function_data_source_name': functions_txt_filename,
    'function_declarations': '\n'.join(function_declarations),
    'parameter_declarations': '\n'.join(sorted(parameter_declarations))
}

insert_functions = []
get_unmangled_builtin = []

def get_shader_version_condition_for_level(level):
    if level == 'ESSL3_1_BUILTINS':
        return 'shaderVersion >= 310'
    elif level == 'ESSL3_BUILTINS':
        return 'shaderVersion >= 300'
    elif level == 'ESSL1_BUILTINS':
        return 'shaderVersion == 100'
    elif level == 'COMMON_BUILTINS':
        return ''
    else:
        raise Exception('Unsupported symbol table level')

for condition in insert_functions_by_condition:
    if condition != 'NO_CONDITION':
        condition_header = '  if ({condition})\n {{'.format(condition = condition)
        insert_functions.append(condition_header)
    for insert_function in insert_functions_by_condition[condition]:
        insert_functions.append(insert_function)
    if condition != 'NO_CONDITION':
        insert_functions.append('}')

for level in levels:
    level_condition = get_shader_version_condition_for_level(level)
    if level_condition != '':
        get_unmangled_builtin.append('if ({condition})\n {{'.format(condition = level_condition))

    for condition, functions in unmangled_function_if_statements.iter_conditions(level):
        if len(functions) > 0:
            if condition != 'NO_CONDITION':
                condition_header = '  if ({condition})\n {{'.format(condition = condition)
                get_unmangled_builtin.append(condition_header.replace('shaderType', 'mShaderType'))

            get_unmangled_builtin_switch = {}
            for function_name, get_unmangled_case in functions.iteritems():
                name_hash = hash32(function_name)
                if name_hash not in get_unmangled_builtin_switch:
                    get_unmangled_builtin_switch[name_hash] = []
                get_unmangled_builtin_switch[name_hash].append(get_unmangled_case['code'])

            get_unmangled_builtin.append('switch(nameHash) {')
            for name_hash, get_unmangled_cases in sorted(get_unmangled_builtin_switch.iteritems()):
                get_unmangled_builtin.append('case 0x' + ('%x' % name_hash) + 'u:\n{')
                get_unmangled_builtin += get_unmangled_cases
                get_unmangled_builtin.append('break;\n}')
            get_unmangled_builtin.append('}')

            if condition != 'NO_CONDITION':
                get_unmangled_builtin.append('}')

    if level_condition != '':
        get_unmangled_builtin.append('}')

get_unmangled_builtin.append('return nullptr;')

output_strings['insert_functions'] = '\n'.join(insert_functions)
output_strings['unmangled_builtin_declarations'] = '\n'.join(sorted(unmangled_builtin_declarations))
output_strings['get_unmangled_builtin'] = '\n'.join(get_unmangled_builtin)
output_strings['script_generated_hash_tests'] = '\n'.join(script_generated_hash_tests.iterkeys())

with open('../../tests/compiler_tests/ImmutableString_test_autogen.cpp', 'wt') as outfile_cpp:
    output_cpp = template_immutablestringtest_cpp.format(**output_strings)
    outfile_cpp.write(output_cpp)

with open('SymbolTable_autogen.cpp', 'wt') as outfile_cpp:
    output_cpp = template_symboltable_cpp.format(**output_strings)
    outfile_cpp.write(output_cpp)
