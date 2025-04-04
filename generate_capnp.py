#!/usr/bin/env python3

import sys
import os
from pathlib import Path
from clang.cindex import Index, CursorKind, TypeKind

###############################################################################
# 1. MAPPING LOGIC
###############################################################################

# For recognized optional base types, map to your custom "OptionalXxx" struct name.
OPTIONAL_TYPE_MAP = {
    "int":    "OptionalInt32",
    "short":  "OptionalShort",
    "float":  "OptionalFloat32",
    "double": "OptionalFloat64",
    "long long":  "OptionalInt64",
    # Add more if desired (e.g. "unsigned char" -> "OptionalUint8", etc.)
}

def parse_boost_optional(typ_spelling):
    """
    If typ_spelling looks like 'boost::optional<int>', return 'int'.
    Otherwise return None.
    """
    # e.g. "boost::optional<int>"
    start = typ_spelling.find('<')
    end = typ_spelling.rfind('>')
    if start == -1 or end == -1 or end <= start:
        return None
    inside = typ_spelling[start+1:end].strip()
    return inside

def map_cpp_type_to_capnp(typ):
    """
    Generic fallback for non-optional types.
    """
    kind = typ.kind

    # Basic numeric
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

    # RECORD might be e.g. std::string, std::vector<int>, etc.
    elif kind == TypeKind.RECORD:
        spelling = typ.spelling
        if "std::basic_string" in spelling:
            return "Text"
        if "std::vector<" in spelling:
            # naive parse
            # e.g. "std::vector<int>" => "List(Int32)"
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
                return "List(Text)"
        # fallback
        return "Text"

    return "Text"

def map_field_type_to_capnp(field_type):
    """
    1) Check if it's boost::optional<T>.
       - If T is recognized, map to "OptionalXxx" struct.
       - Otherwise fallback to "Text" or some other fallback.
    2) Otherwise do normal mapping.
    """
    spelling = field_type.spelling  # e.g. "boost::optional<int>"
    if "boost::optional<" in spelling:
        base_t = parse_boost_optional(spelling)  # e.g. "int"
        if base_t is not None:
            # See if we recognize it in OPTIONAL_TYPE_MAP
            # e.g. base_t = "int" -> "OptionalInt32"
            # The base_t might be "long long", "float", etc.
            # For simplicity, let's do a few naive checks:
            # (You might need more robust logic or clang-based recursion for complex types.)
            # We'll do simple string matching:

            # If the EXACT text is recognized as a key in OPTIONAL_TYPE_MAP:
            if base_t in OPTIONAL_TYPE_MAP:
                return OPTIONAL_TYPE_MAP[base_t]
            # Otherwise fallback
            return "Text"
        else:
            return "Text"
    else:
        # Normal type
        return map_cpp_type_to_capnp(field_type)

###############################################################################
# 2. SCAN THE AST & COLLECT FIELDS
###############################################################################

def process_class(cls_cursor):
    """
    Returns (className, [ (fieldName, capnpType) ]) 
    for fields in the order they appear in the file.
    We skip methods (public or otherwise).
    """
    class_name = cls_cursor.spelling

    # We'll collect fields in the order they're encountered in AST.
    # Clang typically iterates them in declaration order, so that 
    # 1st field in code => 1st in list => gets field #0, etc.
    fields = []
    for child in cls_cursor.get_children():
        if child.kind == CursorKind.FIELD_DECL:
            field_name = child.spelling
            field_type = child.type
            capnp_type = map_field_type_to_capnp(field_type)
            fields.append((field_name, capnp_type))
    
    return class_name, fields

def parse_headers_in_directory(dir_path, clang_args=None):
    """
    Recursively parse all .h files in dir_path.
    Return a list of (className, [ (fieldName, capnpType) ]).
    """
    if clang_args is None:
        clang_args = ['-std=c++17']

    index = Index.create()
    all_classes = []

    p = Path(dir_path)
    for header_file in p.rglob("*.h"):
        translation_unit = index.parse(str(header_file), args=clang_args)
        for c in translation_unit.cursor.get_children():
            if c.kind == CursorKind.CLASS_DECL:
                # We have a top-level class
                cls_name, fields = process_class(c)
                # If it's named & has fields, record it
                if cls_name and fields:
                    all_classes.append((cls_name, fields))
    
    return all_classes

###############################################################################
# 3. GENERATE THE CAP'N PROTO FILE
###############################################################################

def generate_capnp_file(output_path, classes):
    """
    For each class, define a struct. 
    Fields are enumerated in order with ascending indexes (0,1,2...).
    """
    with open(output_path, 'w') as f:
        # Example ID
        f.write('@0x1234_5678_ABCD_EF01;\n\n')

        for (cls_name, fields) in classes:
            f.write(f"struct {cls_name} {{\n")
            for idx, (field_name, capnp_type) in enumerate(fields):
                # Lowercase the field name to avoid potential collisions
                f.write(f"  {field_name.lower()} @{idx} :{capnp_type};\n")
            f.write("}\n\n")

###############################################################################
# 4. MAIN
###############################################################################

def main(argv):
    if len(argv) < 2:
        print("Usage: python generate_capnp.py <directory_of_headers> [<extra_clang_args>...]")
        sys.exit(1)

    dir_path = argv[1]
    clang_args = argv[2:] if len(argv) > 2 else None

    # 1) Parse the headers for classes & fields
    classes = parse_headers_in_directory(dir_path, clang_args)

    if not classes:
        print("No classes with fields found.")
        return

    # 2) Generate the .capnp
    output_file = "generated.capnp"
    generate_capnp_file(output_file, classes)
    print(f"Wrote schema to {output_file}")

if __name__ == "__main__":
    main(sys.argv)
