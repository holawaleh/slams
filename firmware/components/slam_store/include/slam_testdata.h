#pragma once

// ============================================================
// FAKE DATA FOR BENCH TESTING ONLY. Every name, ID, course
// code and timestamp below is invented. Delete this file and
// its call in app_main before any real deployment.
// ============================================================
#include "slam_store.h"

// Fake data so the decision tree can be tested with no backend.
// Replace UID bytes below with cards you actually own.
static inline void slam_load_test_data(void)
{
    static const dir_entry_t dir[] = {
        { {0xE4,0x79,0x4F,0x2A}, 4, 101, 0 },              // your card
        { {0x11,0x22,0x33,0x44}, 4, 102, 0 },              // enrolled, absent
        { {0xAA,0xBB,0xCC,0xDD}, 4, 103, 0 },              // not enrolled
        { {0xDE,0xAD,0xBE,0xEF}, 4, 900, DIR_FLAG_ADMIN }, // admin
    };
    static const roster_entry_t roster[] = {
        { 101, "TEST STUDENT 1" },
        { 102, "TEST STUDENT 2" },
    };
    session_t s = {
        .session_id = 5001,
        .course = "TESTCOURSE",
        .starts_utc = 1758100000,
        .ends_utc   = 1758107200,
        .grace_minutes = 15,
        .active = true,
    };
    slam_dir_load(dir, sizeof(dir)/sizeof(dir[0]), 1);
    slam_roster_load(&s, roster, sizeof(roster)/sizeof(roster[0]));
    slam_set_time(1758100300);   // 5 minutes into the lecture
}


