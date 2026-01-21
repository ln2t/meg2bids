# Contributing to meg2bids

Thank you for your interest in contributing to meg2bids! We welcome contributions from the community.

## Ways to Contribute

- 🐛 Report bugs
- 💡 Suggest new features
- 📝 Improve documentation
- 🔧 Submit code fixes or enhancements
- ✅ Add tests

## Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

### 3. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=meg2bids --cov-report=html

# Run specific test file
pytest tests/test_meg2bids.py
```

### Code Style

We follow PEP 8 style guidelines with some modifications:

```bash
# Format code with black
black meg2bids.py

# Check with flake8
flake8 meg2bids.py

# Check with pylint
pylint meg2bids.py
```

**Style guidelines:**
- Line length: 100 characters (black default)
- Use type hints where possible
- Document functions with docstrings
- Keep functions focused and modular

### Documentation

- Update docstrings for any changed functions
- Update README.md if adding new features
- Add examples for new functionality
- Update docs/ if necessary

## Submitting Changes

### 1. Commit Your Changes

```bash
git add .
git commit -m "Brief description of changes"
```

**Commit message guidelines:**
- Use present tense ("Add feature" not "Added feature")
- Be descriptive but concise
- Reference issues when applicable (#123)

### 2. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 3. Open a Pull Request

- Go to the original repository on GitHub
- Click "New Pull Request"
- Select your fork and branch
- Provide a clear description of changes
- Reference any related issues

**Pull request checklist:**
- [ ] Tests pass locally
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] No merge conflicts

## Reporting Issues

### Bug Reports

When reporting bugs, please include:

1. **Description**: Clear description of the bug
2. **Environment**:
   - OS (Linux, macOS, Windows)
   - Python version
   - meg2bids version
   - MNE version
3. **Steps to reproduce**:
   - Minimal example to reproduce
   - Input files (if possible)
   - Configuration used
4. **Expected behavior**: What should happen
5. **Actual behavior**: What actually happens
6. **Error messages**: Full traceback if applicable

### Feature Requests

When suggesting features, please include:

1. **Use case**: Why this feature is needed
2. **Proposed solution**: How it might work
3. **Alternatives**: Other approaches considered
4. **Examples**: Similar features in other tools

## Code Review Process

1. Maintainers will review your pull request
2. They may request changes or clarifications
3. Once approved, your PR will be merged
4. Your contribution will be acknowledged in release notes

## Community Guidelines

- Be respectful and constructive
- Welcome newcomers and help them get started
- Focus on what is best for the community
- Show empathy towards other contributors

## Questions?

- **Usage questions**: Post on [Neurostars](https://neurostars.org/) with `meg2bids` tag
- **Development questions**: Open a GitHub issue with `question` label
- **General discussion**: Start a GitHub Discussion

## License

By contributing to meg2bids, you agree that your contributions will be licensed under the GNU General Public License v3.0.

## Acknowledgments

Thank you for contributing to meg2bids! Every contribution, no matter how small, helps improve the tool for the entire community.
