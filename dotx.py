#!/usr/bin/env python3

import os
import sys
import yaml
import pprint
import fnmatch
import argparse
from string import Template


Newline = '\n'
Space   = ' '
Dot     = '.'

ModelsDir  = 'Models'
SchemasDir = 'Schemas'
PagesDir   = 'Pages'

ModelTemplate = '''$USING

namespace $NAMESPACE
{$PREFIX
    public class $CLASSNAME
    {
        $FIELDS
    }
}
'''

PageModelTemplate = '''
using $PROJECTNAME.Data;
using $PROJECTNAME.Models;
using Microsoft.AspNetCore.Mvc.RazorPages;
using System.collections.Generic;
using System.Linq;

namespace $NAMESPACE
{
    public class $CLASSNAME : PageModel
    {

    }
}
'''

def _debug(*args):
    print('DEBUG:', *args)

def error(msg):
    print('ERROR: %s' % msg)

def errorExit(msg):
    error(msg)
    exit(1)

def info(msg):
    print(msg)

def addToList(alist, item):
    if item not in alist:
        alist.append(item)

def createFile(filePath, content, overwrite=False):
    dirPath = os.path.split(filePath)[:-1]
    if len(dirPath) > 1:
        dirPath = os.path.join(*dirPath)
        if not os.path.exists(dirPath):
            os.makedirs(dirPath)

    if not os.path.exists(filePath):
        with open(filePath, 'w') as fp:
            fp.write(content)
        info('Created ' + filePath)
    elif overwrite:
        with open(filePath, 'w') as fp:
            fp.write(content)
        info('Overwrite ' + filePath)
    else:
        info('File exists ' + filePath)

AnnotationLibs = {
    'DatabaseGenerated': 'System.ComponentModel.DataAnnotations.Schema',
    'Column': 'System.ComponentModel.DataAnnotations.Schema',
}
AnnotationCommonLib = 'System.ComponentModel.DataAnnotations'
    
def parseAnnotates(data, libs, annotates):
    for row in data:
        if isinstance(row, str):
            annotates.append('[%s]' % row)
        elif isinstance(row, dict):
            for key, value in row.items():
                if value:
                    annotates.append('[%s(%s)]' % (key, value))
                else:
                    annotates.append('[%s]' % key)

                if key in AnnotationLibs:
                    lib = AnnotationLibs[key]
                else:
                    lib = AnnotationCommonLib
            addToList(libs, lib)


class Method(object):
    def __init__(self, data, libs):
        self.name = None
        self.type = None
        self.get = None
        self.set = None
        self.annotates = []

        for key, value in data.items():
            if key == '_@_':
                parseAnnotates(value, libs, self.annotates)
            elif key == '_get_':
                self.get = value
            elif key == '_set_':
                self.set = value
            elif self.name:
                error("Invalid method config '%s'" % key)
            else:
                self.name = key
                self.type = value

    def __repr__(self):
        rs = []
        indent = Newline + Space * 8

        if self.annotates:
            rs.append('')
            rs.extend([x for x in self.annotates])

        rs.append('public %s %s' % (self.type, self.name))
        
        indent = Newline + Space * 12
        spaces = Space * 4
        rs.append('{')
        if self.get:
            rs.append(indent.join([spaces + 'get', '{', spaces, self.get, '}']))
        if self.set:
            rs.append(indent.join([spaces + 'get', '{', spaces, self.set, '}']))
        rs.append('}')

        indent = Newline + Space * 8
        return indent.join(rs)

class Column(object):
    def __init__(self, col, libs):
        colName, colType = '', ''
        annotates = []
        for key, value in col.items():
            if key == '_@_':
                parseAnnotates(value, libs, annotates)
            elif colName:
                error("Invalid column configuration '%s'" % key)
            else:
                colName = key
                colType = value        

        collectionsLib = 'System.Collections.Generic'

        if colName != '_text_':
            if colType.startswith('list<'):
                colType = 'ICollection<%s>' % colType[5:-1]
                addToList(libs, collectionsLib)
            elif colType.startswith('enumerable<'):
                colType = 'IEnumerable<%s>' % colType[11:-1]
                addToList(libs, collectionsLib)

        self.name = colName
        self.type = colType
        self.annotates = annotates

    def __repr__(self):
        rs = []
        indent = Newline + Space * 8

        if self.annotates:
            rs.append('')
            rs.extend([x for x in self.annotates])

        if self.name == '_text_':
            text = indent.join(self.type.split(Newline))
            rs.append(Newline + text)
        else:
            rs.append('public %s %s { get; set; }' % (self.type, self.name))

        return indent.join(rs)

class Model(object):
    def __init__(self, projectName, modelName, modelData):
        self.projectName = projectName
        self.modelName = modelName
        self.filePath = None
        self.classPrefix = None
        self.viewModel = False
        self.cols = []
        self.rels = []
        self.uses = []
        self.relUses = []
        self.methods = []

        self.namespace = '%s.%s' % (projectName, ModelsDir)
        addToList(self.uses, 'System')

        for key, value in modelData.items():
            if key == '_cols_':
                for col in value:
                    self.cols.append(Column(col, self.uses))
            elif key == '_rels_':
                for rel in value:
                    self.rels.append(Column(rel, self.relUses))
            elif key == '_methods_':
                for met in value:
                    self.methods.append(Method(met, self.uses))
            elif key == '_prefix_':
                self.classPrefix = value
            elif key == '_viewModel_':
                self.viewModel = value
            elif key == '_filePath_':
                self.filePath = value
            else:
                error("Invalid model configuration '%s'" % key)

        if self.filePath:
            self.namespace = '%s.%s' % (self.namespace, Dot.join(self.filePath.split('/')))

    def content(self):
        uses = self.uses
        if self.relUses:
            uses.extend(self.relUses)

        using = ''
        if uses:
            uses.sort()
            using = Newline.join('using %s;' % x for x in uses)
        
        prefix = ''
        if self.classPrefix:
            indent = Newline + Space * 4
            prefix = indent + indent.join(self.classPrefix.split(Newline))

        indent = Newline + Space * 8
        fields = [str(col) for col in self.cols]

        if self.rels:
            fields.append('')
            fields.extend([str(rel) for rel in self.rels])

        if self.methods:
            fields.append('')
            fields.extend([str(m) for m in self.methods])

        fields = indent.join(fields).strip()

        namespace = self.namespace
        classname = self.modelName
        return Template(ModelTemplate).substitute(
            USING=using,
            PREFIX=prefix,
            NAMESPACE=self.namespace,
            CLASSNAME=classname,
            FIELDS=fields)

class Schema(object):
    def __init__(self, configFile):
        self.configFile = configFile
        with open(configFile) as fp:
            self.doc = yaml.load(fp)

    def __repr__(self):
        return "Schema: %s" % self.configFile

class ModelCmd(object):
    description = "Create model file"

    def __init__(self):
        parser = argparse.ArgumentParser(description=self.description)
        parser.add_argument('--schema', help='Schema configuration file')
        parser.add_argument('--only', nargs='+', help='Process only specified models')
        parser.add_argument('--overwrite', action='store_true', help='Overwrite existing file')
        parser.add_argument('--no-write', dest='noWrite', action='store_true', help="Don't create file")
        parser.add_argument('--check', action='store_true', help='Check schema configuration')
        parser.add_argument('--dump', action='store_true', help='Dump schema configration')
        self.args = parser.parse_args(sys.argv[2:])

        cwd = os.getcwd()
        projectName = os.path.split(cwd)[-1]
        if not os.path.exists(projectName + '.csproj'):
            errorExit("No project found for '%s'" % projectName)

        self.load_schemas()

        if self.args.dump:
            pp = pprint.PrettyPrinter(indent=2)
            for schema in self.schemas:
                info(schema.configFile)
                pp.pprint(schema.doc)
            return

        if self.args.check:
            for schema in self.schemas:
                info(schema.configFile)
                info(yaml.dump(
                    schema.doc,
                    default_flow_style=False,
                    default_style='',
                    indent=2))
            return

        models = []
        args = self.args
        for schema in self.schemas:
            for modelName, modelData in schema.doc.items():
                if modelName.startswith('__'):
                    continue
                if args.only and modelName not in args.only:
                    continue
                models.append(Model(projectName, modelName, modelData))

        if self.args.noWrite:
            return

        if not os.path.exists(ModelsDir):
            os.makedirs(ModelsDir)

        overwrite = self.args.overwrite
        for model in models:
            filePath = model.filePath
            fileName = model.modelName + '.cs'
            content = model.content()

            if filePath:
            	filePath = os.path.join(ModelsDir, *(filePath.split('/')), fileName)
            else:
            	filePath = os.path.join(ModelsDir, fileName)
            createFile(filePath, content, overwrite)
            
    def load_schemas(self):
        self.schemas = []
        if self.args.schema:
            self.schemas.append(Schema(self.args.schema))
            return

        files = os.listdir(SchemasDir)
        pattern = '*.yaml'
        for entry in files:
            if fnmatch.fnmatch(entry, pattern):
                path = os.path.join(SchemasDir, entry)
                self.schemas.append(Schema(path))

    def createFile(self, fileName, content, customPath=None, overwrite=False):
         if customPath:
             customPath = os.path.join(ModelsDir, *(customPath.split('/')))
             if not os.path.exists(customPath):
                 os.makedirs(customPath)
             filePath = os.path.join(customPath, fileName)
         else:
             filePath = os.path.join(ModelsDir, fileName)

         if not os.path.exists(filePath):
             with open(filePath, 'w') as fp:
                 fp.write(content)
             info('Created ' + fileName)
         elif overwrite:
             with open(filePath, 'w') as fp:
                 fp.write(content)
             info('Overwrite ' + fileName)
         else:
             info('File exists ' + fileName)



class NewFileCmd(object):
    description = 'Create new file from template'

    def __init__(self):
        parser = argparse.ArgumentParser(description=self.description)
        parser.add_argument('--pagemodel', action='store_true', help='Create PageModel file')
        parser.add_argument('--overwrite', action='store_true', help='Overwrite existing file')
        parser.add_argument('fileName', help='file name or file path')
        args = parser.parse_args(sys.argv[2:])

        if args.pagemodel:
            self.create_pagemodel(args)

    def create_pagemodel(self, args):
        fileName = args.fileName

        cwd = os.getcwd()
        projectName = os.path.split(cwd)[-1]

        paths = fileName.split('/')
        classname = paths[-1]

        if len(paths) == 1:
            namespace = Dot.join([projectName, PagesDir])
        else:
            namespace = Dot.join([projectName, PagesDir, Dot.join(paths[:-1])])

        dirPath = os.path.join(PagesDir, *paths[:-1])
        if not os.path.exists(dirPath):
            os.makedirs(dirPath)

        content = Template(PageModelTemplate).substitute(
            PROJECTNAME=projectName,
            NAMESPACE=namespace,
            CLASSNAME=classname)

        filePath = os.path.join('Pages', *paths) + '.cshtml.cs'

        createFile(filePath, content, args.overwrite);


CmdList = {
    'model': ModelCmd,
    'newfile': NewFileCmd,
}


usage = '''dotx <command> [<args>]

command are:\n    %s   
''' % '\n    '.join(['%s: %s' % (k, ModelCmd.description) for k, v in CmdList.items()])


class Dotx(object):
    def __init__(self):
        parser = argparse.ArgumentParser( usage=usage)
        parser.add_argument('command', help='subcommand')
        args = parser.parse_args(sys.argv[1:2])

        if args.command not in CmdList:
            print('unrecognised command')
            parser.print_help()
            exit(0)

        CmdList[args.command]()


if __name__ == '__main__':
    Dotx()
