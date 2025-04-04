# C++ to Cap'n Proto Generation Tool

This repository contains a Python script that scans a directory of C++ headers and automatically generates a Cap'n Proto `.capnp` schema:

- **Classes** are discovered in the parsed headers.
  
- **Fields** in each class are enumerated in declaration order, giving them ascending field numbers (starting at 0).
  
- **Boost Optionals** are handled in two ways:
  
  1. **Built-in numeric** types (`int`, `float`, etc.) map to preexisting optional types (e.g. `OptionalInt32`, `OptionalFloat32`).
    
  2. **User-defined classes** automatically generate a stub class if missing, and an `Optional` wrapper for them (e.g. `OptionalMyClass`).
    

## Features

1. **C++ AST Parsing**: Uses [libclang](https://clang.llvm.org/docs/Tooling.html) via Python bindings to parse C++ headers.
  
2. **Declaration-Order Field Numbering**: The script preserves the field order from your C++ source.
  
3. **Support for `boost::optional<T>`**:
  
  - If `T` is a recognized built-in, it is mapped to `OptionalXxx` (like `OptionalInt32`).
    
  - If `T` is an unknown user-defined class, a stub is created for `T` (no fields) and an optional wrapper `OptionalT` is also created.
    
4. **Generated Output**: Creates a single file `generated.capnp` with your classes as Cap'n Proto structs.
  

## Dependencies

- **Python 3.6+**
  
- **libclang** (matching the version of Clang you have installed)
  
- **Python clang bindings**:
  
  ```bash
  pip install clang
  ```
  

## Usage

1. **Install Requirements**:
  
  ```bash
  pip install clang
  ```
  
  Make sure you have `libclang` installed on your system. For example:
  
  ```bash
  apt-get install libclang-12-dev
  ```
  
2. **Place your C++ headers** in a directory (recursively scanned).
  
3. **Run the Script**:
  
  ```bash
  python generate_capnp.py <directory_of_headers> [<extra_clang_args>...]
  ```
  
  For instance:
  
  ```bash
  python generate_capnp.py ./include -I/usr/include -I/usr/local/include
  ```
  
4. **View `generated.capnp`**:
  
  - The file includes a top-level `@0x1234_5678_ABCD_EF01;` ID.
    
  - Each discovered class is written as:
    
    ```capnp
    struct MyClass {
     fielda @0 :Int32;
     fieldb @1 :Text;
    }
    ```
    
  - Any optional wrappers you needed are appended at the end, e.g.:
    
    ```capnp
    struct OptionalMyClass {
     value @0 :MyClass;
    }
    ```
    

## Limitations

- **No stable versioning**: Field numbers are purely based on the order in the C++ source each time you run.
  
- **Basic type inference**: Only minimal detection for `std::string`, `std::vector<T>`, or numeric types.
  
- **Stub classes**: If a user-defined type `T` is encountered only as `boost::optional<T>`, we generate `T` as an empty struct unless its definition also appears in your headers.
  
- **No inheritance or method-based property detection**: We only handle direct `FIELD_DECL` in C++ classes.
  

## Example

Given a header:

```cpp
#ifndef MYCLASS_H
#define MYCLASS_H

#include <boost/optional.hpp>
#include <string>

class MyClass {
private:
    boost::optional<int> id;
    double temperature;
    std::string name;
    boost::optional<class Nested> obj;
};

class Nested {
private:
    int x;
    float y;
};

#endif
```

- **MyClass** has four fields:
  
  1. `boost::optional<int>` => `OptionalInt32`
    
  2. `double` => `Float64`
    
  3. `std::string` => `Text`
    
  4. `boost::optional<class Nested>` => `OptionalNested`
    
- **Nested** has two fields: `int x` => `Int32`, `float y` => `Float32`.
  

Running:

```bash
python generate_capnp.py ./include
```

**Output** might look like:

```capnp
@0x1234_5678_ABCD_EF01;

struct MyClass {
  id @0 :OptionalInt32;
  temperature @1 :Float64;
  name @2 :Text;
  obj @3 :OptionalNested;
}

struct Nested {
  x @0 :Int32;
  y @1 :Float32;
}

struct OptionalNested {
  value @0 :Nested;
}
```

## Contributing

Contributions to improve the type inference, add inheritance support, or support more advanced C++ features are welcome.

## License

[MIT License](https://chatgpt.com/g/g-p-677791f734b481919904f7981a9a3745-caelum/c/LICENSE) (or specify your own license).
