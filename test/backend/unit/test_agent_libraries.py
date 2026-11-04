"""Import resolution uses installed headers, canonical identities and app policy."""
import unittest
from unittest.mock import AsyncMock
from app.agent.libraries import Library, imports, resolve
from app.agent.settings import AgentError


def lib(name,headers,architecture='avr',deps=(),version='1.0',core=False):
    return Library(name,version,(architecture,),frozenset(headers),deps,core)


def source(text):return [{'name':'sketch.ino','content':text}]


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    def test_only_real_imports_not_comments_strings_or_local_files(self):
        files=source('// #include <Bad.h>\n/*\n#include <Bad2.h>\n*/\nconst char* s=R"(#include <Bad3.h>)";\n#include <Good.h>\n#include "helper.h"\n')
        files.append({'name':'helper.h','content':'#include <Other.h>\n'})
        self.assertEqual(imports(files),['Good.h','Other.h'])

    async def test_canonical_alias_and_transitive_dependencies(self):
        available=[lib('LiquidCrystal I2C',['LiquidCrystal_I2C.h'],deps=('Wire',)),lib('Wire',['Wire.h'],core=True)]
        result=await resolve(source('#include <LiquidCrystal_I2C.h>\n'),['LiquidCrystal_I2C'],'avr',loader=lambda:available,index_loader=lambda:[])
        self.assertEqual(result['libraries'],['LiquidCrystal I2C'])
        self.assertEqual(len(result['resolved']),2)

    async def test_actual_import_supplies_manifest_without_model_library_call(self):
        result=await resolve(source('#include <Servo.h>\n'),[],'avr',loader=lambda:[lib('Servo',['Servo.h'])])
        self.assertEqual(result['libraries'],['Servo'])

    async def test_versions_and_unknown_private_declarations_are_preserved(self):
        result=await resolve(source('#include <Servo.h>\n'),['Servo@1.0','Private@7.0'],'avr',
            loader=lambda:[lib('Servo',['Servo.h']),lib('Servo',['Servo.h'],version='2.0')],index_loader=lambda:[])
        self.assertEqual(result['libraries'],['Servo@1.0','Private@7.0'])

    async def test_esp32_library_uses_architecture_and_does_not_regress_to_avr(self):
        available=[lib('Servo',['Servo.h']),lib('ESP32Servo',['ESP32Servo.h'],'esp32')]
        result=await resolve(source('#include <ESP32Servo.h>\n'),[],'esp32',loader=lambda:available)
        self.assertEqual(result['libraries'],['ESP32Servo'])
        with self.assertRaises(AgentError) as caught:
            await resolve(source(''),['Servo'],'esp32',loader=lambda:available,index_loader=lambda:[])
        self.assertEqual(caught.exception.code,'library_incompatible')

    async def test_ambiguity_is_not_silently_resolved(self):
        with self.assertRaises(AgentError) as caught:
            await resolve(source('#include <LCD.h>\n'),[],'avr',loader=lambda:[lib('One',['LCD.h']),lib('Two',['LCD.h'])])
        self.assertEqual(caught.exception.code,'library_ambiguous')
        self.assertEqual(caught.exception.details['candidates'],['One','Two'])

    async def test_unique_cached_identity_installs_via_managed_owner_then_verifies_header(self):
        available=[]
        async def install(name,version,user):
            self.assertEqual((name,version,user),('Servo','1.0','original-owner'))
            available.append(lib('Servo',['Servo.h']));return {'success':True}
        result=await resolve(source('#include <Servo.h>\n'),[],'avr',allow_install=True,user='original-owner',
            loader=lambda:available,index_loader=lambda:[{'name':'Servo','version':'1.0','architectures':['avr']}],installer=install)
        self.assertEqual(result['libraries'],['Servo']);self.assertEqual(len(result['installed']),1)
        self.assertEqual(result['unknown_headers'],[])

    async def test_unverified_header_is_never_claimed_installed_and_policy_denial_is_kept(self):
        installer=AsyncMock(return_value={'success':False,'error':'Sign in to install this library'})
        with self.assertRaises(AgentError) as caught:
            await resolve(source('#include <Servo.h>\n'),[],'avr',allow_install=True,
                loader=lambda:[],index_loader=lambda:[{'name':'Servo','version':'1.0','architectures':['avr']}],installer=installer)
        self.assertEqual(caught.exception.code,'library_install_failed')
        self.assertIn('Sign in',str(caught.exception))
        self.assertIn('Changing the sketch cannot repair',caught.exception.details['next_action'])
        installer.assert_awaited_once()

    async def test_wrong_header_reports_verified_exports_instead_of_a_blind_library_switch(self):
        installed=[lib('Display',['DisplayDriver.h','src/DisplayDriver.h'])]
        with self.assertRaises(AgentError) as caught:
            await resolve(source('#include <Display.h>\n'),[],'avr',allow_install=True,loader=lambda:installed,
                index_loader=lambda:[{'name':'Display','version':'1.0','architectures':['avr']}])
        self.assertEqual(caught.exception.code,'library_header_missing')
        self.assertEqual(caught.exception.details['exported_headers'],['DisplayDriver.h'])
        self.assertIn('Correct the #include',caught.exception.details['next_action'])
        self.assertNotIn('/src',str(caught.exception.details))

    async def test_unknown_import_does_not_trigger_guessed_download(self):
        installer=AsyncMock()
        result=await resolve(source('#include <Unrelated.h>\n'),[],'avr',allow_install=True,
            loader=lambda:[],index_loader=lambda:[{'name':'Random','architectures':['avr']}],installer=installer)
        installer.assert_not_awaited();self.assertEqual(result['unknown_headers'],['Unrelated.h'])
