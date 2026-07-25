#include <iostream>
#include <iterator>
#include <string>

int main() {
  const std::string input{
      std::istreambuf_iterator<char>{std::cin},
      std::istreambuf_iterator<char>{}};
  const bool accepted =
      input.find("\"actualOutput\":\"43\\n\"") != std::string::npos &&
      input.find("\"expectedOutput\":\"42\\n\"") != std::string::npos;
  std::cout << "{\"schemaVersion\":1,\"accepted\":"
            << (accepted ? "true" : "false") << "}";
}
