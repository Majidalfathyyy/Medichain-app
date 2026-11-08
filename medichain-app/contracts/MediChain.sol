// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title MediChain
/// @notice Mencatat HASH rekam medis dan biosignal (bukan data mentah), versi, waktu, dan izin akses per peran.
/// @dev Seluruh identifier adalah bytes32 turunan (SHA-256), tidak memuat data pribadi.
///      Prototipe untuk testnet; belum diaudit pihak ketiga.
contract MediChain {
    struct Rec {
        bytes32 hashRecord;
        bytes32 hashEcg;
        uint32 version;
        uint64 timestamp;
        address by;
    }

    address public owner;
    bool public paused;
    mapping(address => bool) public writers;                 // akun backend yang boleh menulis
    mapping(bytes32 => Rec) private recs;
    mapping(bytes32 => mapping(bytes32 => bool)) public access; // recordKey => roleHash => diizinkan

    event RecordRegistered(bytes32 indexed key, bytes32 hashRecord, bytes32 hashEcg, address indexed by);
    event RecordImported(bytes32 indexed key, uint32 initialVersion, bytes32 hashRecord, bytes32 hashEcg, address indexed by);
    event RecordUpdated(bytes32 indexed key, uint32 version, bytes32 oldHashRecord, bytes32 oldHashEcg,
                        bytes32 newHashRecord, bytes32 newHashEcg, address indexed by);
    event AccessGranted(bytes32 indexed key, bytes32 indexed role, address indexed by);
    event AccessRevoked(bytes32 indexed key, bytes32 indexed role, address indexed by);
    event AccessLogged(bytes32 indexed key, string action, address indexed by, uint64 timestamp);
    event OwnershipTransferred(address indexed from, address indexed to);
    event WriterSet(address indexed who, bool allowed);
    event Paused(bool state);

    error NotOwner();
    error NotWriter();
    error IsPaused();
    error ZeroHash();
    error AlreadyRegistered();
    error NotRegistered();
    error InvalidVersion();

    modifier onlyOwner() { if (msg.sender != owner) revert NotOwner(); _; }
    modifier onlyWriter() { if (!writers[msg.sender]) revert NotWriter(); if (paused) revert IsPaused(); _; }

    constructor() {
        owner = msg.sender;
        writers[msg.sender] = true;
        emit WriterSet(msg.sender, true);
    }

    // ---- administrasi ----
    function transferOwnership(address to) external onlyOwner {
        require(to != address(0), "zero address");
        emit OwnershipTransferred(owner, to);
        owner = to;
    }

    function setWriter(address who, bool allowed) external onlyOwner {
        writers[who] = allowed;
        emit WriterSet(who, allowed);
    }

    function setPaused(bool state) external onlyOwner {  // circuit breaker bila kunci backend bocor
        paused = state;
        emit Paused(state);
    }

    // ---- rekam ----
    function registerRecord(bytes32 key, bytes32 hashRecord, bytes32 hashEcg) external onlyWriter {
        if (hashRecord == 0 || hashEcg == 0) revert ZeroHash();
        if (recs[key].version != 0) revert AlreadyRegistered();
        recs[key] = Rec(hashRecord, hashEcg, 1, uint64(block.timestamp), msg.sender);
        emit RecordRegistered(key, hashRecord, hashEcg, msg.sender);
    }

    /// @notice Import a current DB snapshot while preserving its existing version counter.
    /// @dev This anchors only the current state; prior versions are not reconstructed on-chain.
    function registerRecordAtVersion(bytes32 key, bytes32 hashRecord, bytes32 hashEcg, uint32 initialVersion)
        external onlyWriter
    {
        if (hashRecord == 0 || hashEcg == 0) revert ZeroHash();
        if (initialVersion == 0) revert InvalidVersion();
        if (recs[key].version != 0) revert AlreadyRegistered();
        recs[key] = Rec(hashRecord, hashEcg, initialVersion, uint64(block.timestamp), msg.sender);
        emit RecordImported(key, initialVersion, hashRecord, hashEcg, msg.sender);
    }

    function updateRecord(bytes32 key, bytes32 hashRecord, bytes32 hashEcg) external onlyWriter {
        if (hashRecord == 0 || hashEcg == 0) revert ZeroHash();
        Rec storage r = recs[key];
        if (r.version == 0) revert NotRegistered();
        emit RecordUpdated(key, r.version + 1, r.hashRecord, r.hashEcg, hashRecord, hashEcg, msg.sender);
        r.hashRecord = hashRecord;
        r.hashEcg = hashEcg;
        r.version += 1;
        r.timestamp = uint64(block.timestamp);
        r.by = msg.sender;
    }

    /// @return hashRecord, hashEcg, version (0 bila belum terdaftar), timestamp
    function getRecord(bytes32 key) external view returns (bytes32, bytes32, uint32, uint64) {
        Rec storage r = recs[key];
        return (r.hashRecord, r.hashEcg, r.version, r.timestamp);
    }

    function verifyRecord(bytes32 key, bytes32 hashRecord, bytes32 hashEcg) external view returns (bool recordOk, bool ecgOk) {
        Rec storage r = recs[key];
        if (r.version == 0) return (false, false);
        return (r.hashRecord == hashRecord, r.hashEcg == hashEcg);
    }

    // ---- akses ----
    function grantAccess(bytes32 key, bytes32 role) external onlyWriter {
        if (recs[key].version == 0) revert NotRegistered();
        access[key][role] = true;
        emit AccessGranted(key, role, msg.sender);
    }

    function revokeAccess(bytes32 key, bytes32 role) external onlyWriter {
        access[key][role] = false;
        emit AccessRevoked(key, role, msg.sender);
    }

    function logAccess(bytes32 key, string calldata action) external onlyWriter {
        emit AccessLogged(key, action, msg.sender, uint64(block.timestamp));
    }
}
