#!/usr/bin/env python3

import sys
import os
from pathlib import Path
from clang.cindex import Index, CursorKind, TypeKind

###############################################################################
# PURPOSE:
# This script parses a directory of C++ header files.
# For each top-level class, it collects fields in declaration order and generates
# a corresponding Cap'n Proto struct. Fields get incremental indices (0,1,2,...)
# in that order.

# If it encounters boost::optional<SomeClass>, and SomeClass is not already known
# or doesn't map to a built-in type, it creates a new stub struct for 'SomeClass'
# (with no fields) if needed. Then it also creates an 'OptionalSomeClass' wrapper
# struct with 'value @0 :SomeClass;'
#
# For recognized built-in numeric types inside a boost::optional, we continue to
# map them to 'OptionalInt32', 'OptionalFloat32', etc. as before.
###############################################################################

# For recognized optional base types, map to your custom "OptionalXxx" struct name.
# If a field is boost::optional<int>, we use OptionalInt32, etc.
OPTIONAL_TYPE_MAP = {
    "int":    "OptionalInt32",
    "short":  "OptionalShort",
    "float":  "OptionalFloat32",
    "double": "OptionalFloat64",
    "long long":  "OptionalInt64",
    # Add more if desired (e.g. "unsigned char" -> "OptionalUint8", etc.)
}

# We will store discovered classes and optional wrappers:
# discovered_classes: Dict[str, List[ (fieldName, capnpType) ] ]
#   e.g. { "MyClass": [("fieldA", "Int32"), ("fieldB", "Text")], ...}
# discovered_optionals: Dict[str, str]
#   e.g. { "OptionalFoo": "Foo" } means we define struct OptionalFoo { value @0 :Foo; }

###############################################################################
# 1. HELPER FUNCTIONS
###############################################################################

def parse_boost_optional(typ_spelling):
    """
    If typ_spelling looks like 'boost::optional<int>', return 'int'.
    Otherwise return None.
    """
    start = typ_spelling.find('<')
    end = typ_spelling.rfind('>')
    if start == -1 or end == -1 or end <= start:
        return None
    inside = typ_spelling[start+1:end].strip()
    return inside

def map_builtin_cpp_type_to_capnp(kind):
    """
    Maps a clang TypeKind for built-in numeric/boolean to a basic Cap'n Proto type.
    Returns a string like "Int32", "Float64", etc., or None if not recognized.
    """
    if kind in (TypeKind.INT, TypeKind.LONG, TypeKind.SHORT):
        return "Int32"
    elif kind in (TypeKind.UINT, TypeKind.ULONG, TypeKind.USHORT):
        return "UInt32"
    elif kind == TypeKind.LONGLONG:
        return "Int64"
    elif kind == TypeKind.ULONGLONG:
        return "UInt64"
    elif kind == TypeKind.FLOAT:
        return "Float32"
    elif kind == TypeKind.DOUBLE:
        return "Float64"
    elif kind == TypeKind.BOOL:
        return "Bool"
    return None

def map_field_type_to_capnp(field_type, discovered_classes, discovered_optionals):
    """
    Main function to map a clang field type to a Cap'n Proto type string.

    1) If it's boost::optional<T>:
       - If T is recognized built-in (e.g. int -> OptionalInt32) or if T is a known class,
         we handle accordingly.
       - If T is not known but is a class name from the code, create a new stub for it.
         Then also create an 'OptionalT' wrapper struct with 'value @0 :T;'.
    2) Otherwise, if it's a built-in numeric/boolean, map to Int32/Float64 etc.
    3) If it's RECORD type for e.g. std::string, std::vector, or a user-defined class,
       we either treat them as Text, List(...), or a newly discovered empty struct.
    """
    spelling = field_type.spelling  # e.g. "boost::optional<int>"
    kind = field_type.kind

    # Check if it's boost::optional<...>
    if "boost::optional<" in spelling:
        base_t = parse_boost_optional(spelling)
        if base_t is None:
            return "Text"  # fallback
        # e.g. base_t = "int", "MyClass", etc.

        # If base_t is recognized as a built-in in OPTIONAL_TYPE_MAP, use that
        if base_t in OPTIONAL_TYPE_MAP:
            return OPTIONAL_TYPE_MAP[base_t]

        # Otherwise, we interpret base_t as a class name.
        # 1) If we already discovered that class, great.
        # 2) If not, create a new stub class.
        if base_t not in discovered_classes:
            # Create a stub (no fields)
            discovered_classes[base_t] = []

        # Now define "Optional" + base_t if not already done
        opt_name = "Optional" + base_t
        if opt_name not in discovered_optionals:
            discovered_optionals[opt_name] = base_t

        return opt_name

    # If not boost::optional, see if it's a built-in numeric/boolean
    builtin_map = map_builtin_cpp_type_to_capnp(kind)
    if builtin_map:
        return builtin_map

    # Otherwise, handle RECORD type (class, struct, or known stl)
    if kind == TypeKind.RECORD:
        # e.g. std::string, std::vector, or user-defined class
        # We'll do some naive checks for stl.
        if "std::basic_string" in spelling:
            return "Text"
        if "std::vector<" in spelling:
            # naive parse of the template param
            start = spelling.find('<')
            end = spelling.rfind('>')
            if start != -1 and end != -1:
                inner = spelling[start+1:end].strip()
                if "int" in inner:
                    return "List(Int32)"
                elif "float" in inner:
                    return "List(Float32)"
                elif "double" in inner:
                    return "List(Float64)"
                elif "bool" in inner:
                    return "List(Bool)"
                elif "std::string" in inner:
                    return "List(Text)"
                # fallback
                return "List(Text)"

        # If it's a user-defined class name. e.g. "MyClass"
        # We'll see if we have discovered it. If not, create a stub.
        if spelling not in discovered_classes:
            discovered_classes[spelling] = []
        # Then we just reference it by name in the schema.
        return spelling

    # fallback
    return "Text"

###############################################################################
# 2. GLOBAL STORAGE
###############################################################################
discovered_classes = {}   # name -> list of fields
discovered_optionals = {} # optionalName -> baseName

###############################################################################
# 3. AST TRAVERSAL
###############################################################################
def process_class(cls_cursor):
    """
    Collects fields in declaration order.
    Returns (className, [ (fieldName, capnpType) ])
    """
    class_name = cls_cursor.spelling
    fields = []

    for child in cls_cursor.get_children():
        if child.kind == CursorKind.FIELD_DECL:
            field_name = child.spelling
            field_type = child.type
            capnp_type = map_field_type_to_capnp(field_type, discovered_classes, discovered_optionals)
            fields.append((field_name, capnp_type))

    return class_name, fields

def parse_headers_in_directory(dir_path, clang_args=None):
    """
    Recursively parse all .h files in dir_path.
    Return a list of (className, [(fieldName, capnpType)]).
    """
    if clang_args is None:
        clang_args = ['-std=c++17']

    index = Index.create()
    results = []

    p = Path(dir_path)
    for header_file in p.rglob("*.h"):
        translation_unit = index.parse(str(header_file), args=clang_args)
        for c in translation_unit.cursor.get_children():
            if c.kind == CursorKind.CLASS_DECL:
                cls_name, fields = process_class(c)
                if cls_name and fields:
                    # store in global discovered_classes as well
                    discovered_classes[cls_name] = fields
                    results.append((cls_name, fields))
    return results

###############################################################################
# 4. GENERATE CAPNP FILE
###############################################################################
def generate_capnp_file(output_path):
    """
    We'll write out:
      1) A top-level unique ID.
      2) All discovered classes as 'struct ClassName { ... }'.
      3) All optional wrappers as 'struct OptionalClassName { value @0 :ClassName; }'.
    """
    with open(output_path, 'w') as f:
        f.write('@0x1234_5678_ABCD_EF01;\n\n')

        # First, write out all discovered classes in alphabetical order.
        for cls_name in sorted(discovered_classes.keys()):
            fields = discovered_classes[cls_name]
            f.write(f"struct {cls_name} {{\n")
            for idx, (field_name, capnp_type) in enumerate(fields):
                f.write(f"  {field_name.lower()} @{idx} :{capnp_type};\n")
            f.write("}\n\n")

        # Next, write out all optional wrappers.
        for opt_name in sorted(discovered_optionals.keys()):
            base_name = discovered_optionals[opt_name]
            f.write(f"struct {opt_name} {{\n")
            f.write(f"  value @0 :{base_name};\n")
            f.write("}\n\n")

###############################################################################
# 5. MAIN
###############################################################################
def main(argv):
    if len(argv) < 2:
        print("Usage: python generate_capnp.py <directory_of_headers> [<extra_clang_args>...]")
        sys.exit(1)

    dir_path = argv[1]
    clang_args = argv[2:] if len(argv) > 2 else None

    # 1) Parse the headers
    parse_headers_in_directory(dir_path, clang_args)

    # 2) Generate the .capnp
    output_file = "generated.capnp"
    generate_capnp_file(output_file)
    print(f"Wrote schema to {output_file}")

if __name__ == "__main__":
    main(sys.argv)
